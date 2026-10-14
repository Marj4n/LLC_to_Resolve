"""Marj4n LLC to Resolve: zero-video-copy, multitrack timeline generator."""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path
from xml.etree import ElementTree

from converter import (ConversionError, parse_llc, probe, duration_from_probe,
                       extract_audio, audio_names, generate_xml, save_text_atomic,
                       frames)

CONFIG_FILE = Path(__file__).resolve().parent / "config.json"


def config_read() -> dict:
    if not CONFIG_FILE.exists():
        raise ConversionError(f"Missing config.json: {CONFIG_FILE}")
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConversionError(f"Invalid config.json: {exc}") from exc
    for name in ("source_dir", "llc_dir", "output_dir", "audio_dir"):
        if not cfg.get(name):
            raise ConversionError(f"config.json needs '{name}'")
    return cfg


def rec_id(raw: Path, source_dir: Path) -> str:
    files = sorted(source_dir.glob("*.mkv"), key=lambda p: p.name.casefold())
    ids = [p.name.casefold() for p in files]
    try:
        return f"REC{ids.index(raw.name.casefold()) + 1:02d}"
    except ValueError as exc:
        raise ConversionError(f"Missing raw footage in source_dir: {raw.name}") from exc


def summary_csv(segments, fps: int, path: Path):
    rows = ["segment,source_start_seconds,source_end_seconds,source_start_frame,source_end_frame,duration_frames,source_label"]
    for idx, item in enumerate(segments, 1):
        a, b = frames(item.start, fps), frames(item.end, fps)
        # Use csv.writer because names may include commas or quotes.
        from io import StringIO
        tmp = StringIO()
        writer = csv.writer(tmp, lineterminator="")
        writer.writerow([idx,str(item.start),str(item.end),a,b,b-a,item.name])
        rows.append(tmp.getvalue())
    save_text_atomic(path, "\n".join(rows) + "\n")


def convert_one(llc_path: Path, cfg: dict, *, xml_only: bool = False, test_count: int = 3) -> dict:
    source_dir = Path(cfg["source_dir"])
    dest_dir = Path(cfg["output_dir"])
    audio_dir = Path(cfg["audio_dir"])
    if not llc_path.is_file():
        raise ConversionError(f"Cannot find selection .llc: {llc_path}")
    if not source_dir.is_dir():
        raise ConversionError(f"Raw folder does not exist: {source_dir}")
    filename, segments = parse_llc(llc_path)
    mkv = source_dir / filename
    if not mkv.is_file():
        raise ConversionError(f"Expected raw MKV at: {mkv}\nDo not rename it after editing in LosslessCut.")

    fps = int(cfg.get("fps", 60))
    width = int(cfg.get("width", 1920))
    height = int(cfg.get("height", 1080))
    label = rec_id(mkv, source_dir)
    print(f"\n{'='*65}\n[{label}] {mkv.name}\n[LLC] {llc_path.name}: {len(segments)} selected cuts")
    metadata = probe(mkv)
    duration = duration_from_probe(metadata)
    if max(item.end for item in segments) > duration + 1:
        raise ConversionError(f"A cut ends past the raw video duration {duration}s. Recheck selection.")

    game_name, mic_name = audio_names(label)
    game_file, mic_file = audio_dir / game_name, audio_dir / mic_name
    if not xml_only:
        game_file, mic_file = extract_audio(
            mkv, audio_dir, label, metadata,
            game_index=int(cfg.get("game_audio_index",2)),
            mic_index=int(cfg.get("mic_audio_index",1)),
        )
    else:
        if not (game_file.is_file() and mic_file.is_file()):
            raise ConversionError("--xml-only requires previously extracted game and mic audio files.")
    tag = mkv.stem.replace(" ", "_")
    folder = dest_dir / f"{label}_{tag}"
    folder.mkdir(parents=True, exist_ok=True)
    generated = {}
    for kind, selected in (("TEST_3_Cuts",segments[:test_count]), ("FULL_Cuts",segments)):
        if not selected:
            continue
        name = f"{label} - {len(selected)} Cuts - Game and Mic" + (" TEST" if kind.startswith("TEST") else "")
        xml_text, stats = generate_xml(str(mkv), str(game_file), str(mic_file), selected,
                                       fps=fps, width=width, height=height, source_duration=duration,
                                       timeline_name=name, recording_id=label)
        xml_path = folder / f"{label}_{tag}_{kind}.fcpxml"
        save_text_atomic(xml_path, xml_text)
        # Parse the generated XML again to catch serialization failures.
        parsed = ElementTree.parse(xml_path)
        count = len(parsed.findall(".//spine/asset-clip"))
        if count != len(selected):
            raise ConversionError(f"XML validation failed: {count} clips, expected {len(selected)}.")
        generated[kind] = str(xml_path)
        print(f"[XML_OK] {kind}: {stats['clip_count']} cuts / {stats['total_seconds']:.3f}s")
        print(f"         {xml_path}")

    summary_csv(segments, fps, folder / f"{label}_segments.csv")
    manifest = {"recording":label, "llc":str(llc_path), "mkv":str(mkv),
                "audio_game":str(game_file), "audio_mic":str(mic_file),
                "fps":fps, "selected_cuts":len(segments), "xml":generated,
                "notes":"This FCPXML follows the validated REC01 layout. Resolve may add embedded mixed A1 from MKV; MUTE A1 and verify independent GAME/MIC tracks by ear. Do not delete original MKV."}
    save_text_atomic(folder / f"{label}_manifest.json", json.dumps(manifest,indent=2,ensure_ascii=False)+"\n")
    return manifest


def pick_file(start: str) -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root=tk.Tk();root.withdraw()
        filename = filedialog.askopenfilename(title="Select LosslessCut .llc",initialdir=start,
                    filetypes=[("LosslessCut projects", "*.llc"), ("All files","*.*")])
        root.destroy()
        return Path(filename) if filename else None
    except Exception as exc:
        raise ConversionError(f"Could not open file chooser: {exc}. Use --llc path instead.") from exc


def run(args=None) -> int:
    parser=argparse.ArgumentParser(description="Create DaVinci Resolve multitrack FCPXML from LosslessCut selections; original footage stays untouched.")
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument("--llc",type=Path,help="One LosslessCut .llc")
    mode.add_argument("--all",action="store_true",help="Convert every .llc in configured llc_dir")
    parser.add_argument("--xml-only",action="store_true",help="Reuse existing extracted audio; no FFmpeg extraction")
    parser.add_argument("--test-count",type=int,default=3,help="Number of clips in test timeline (default 3)")
    parsed=parser.parse_args(args)
    if parsed.test_count < 1:
        parser.error("--test-count must be >= 1")
    try:
        cfg=config_read()
        if parsed.all:
            llcs=sorted(Path(cfg["llc_dir"]).glob("*.llc"),key=lambda p:p.name.casefold())
            if not llcs:
                raise ConversionError(f"No .llc found in {cfg['llc_dir']}")
        elif parsed.llc:
            llcs=[parsed.llc]
        else:
            chosen=pick_file(cfg["llc_dir"])
            if chosen is None:
                print("File selection cancelled.")
                return 0
            llcs=[chosen]
        print(f"Processing {len(llcs)} LLC file(s). Raw footage will not be modified.")
        ok,failed=0,0
        for path in llcs:
            try:
                convert_one(path,cfg,xml_only=parsed.xml_only,test_count=parsed.test_count)
                ok+=1
            except (ConversionError,OSError,ValueError) as exc:
                print(f"\n[ERROR] {path.name}: {exc}\n",file=sys.stderr)
                failed+=1
                if not parsed.all:
                    break
        print(f"\n[DONE] {ok} succeeded, {failed} failed.\n"
              "Import TEST FCPXML in Resolve first; verify timing and both audio tracks.\n"
              "Keep original MKVs and .llc selections until the video is finished.")
        return 1 if failed else 0
    except (ConversionError,OSError) as exc:
        print(f"[ERROR] {exc}",file=sys.stderr)
        return 1


if __name__=="__main__":
    sys.exit(run())
