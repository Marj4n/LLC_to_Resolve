"""LosslessCut selection -> DaVinci Resolve FCPXML 1.8.

Uses the nested asset-clip layout validated in Resolve Studio 21 for Minecraft
Recording 01. The original MKV is only referenced, never rewritten.
"""
from __future__ import annotations

import json
import re
import subprocess
import shutil
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path, PureWindowsPath
from urllib.parse import quote
from xml.etree.ElementTree import Element, SubElement, indent, tostring


class ConversionError(RuntimeError):
    """A user-actionable conversion failure."""


@dataclass(frozen=True)
class Segment:
    start: Decimal
    end: Decimal
    name: str = ""


def _field(text: str, field: str) -> str | None:
    match = re.search(rf"(?<![\w]){field}\s*:\s*(['\"])((?:\\.|(?!\1).)*?)\1", text, flags=re.S)
    if match:
        value = match.group(2)
        # LosslessCut normally writes plain strings. Only unescape simple quotes
        # and backslashes, without evaluating arbitrary JSON5 or source code.
        return re.sub(r"\\(['\"\\])", r"\1", value)
    return None


def parse_llc(path: Path) -> tuple[str, list[Segment]]:
    """Read LosslessCut's JSON5-like .llc (no third-party packages required)."""
    raw = path.read_text(encoding="utf-8-sig")
    filename = _field(raw, "mediaFileName")
    if not filename:
        raise ConversionError(f"Cannot find mediaFileName in {path.name}.")
    if filename in (".", "..") or any(c in filename for c in ("/", "\\")):
        raise ConversionError("Unexpected mediaFileName: expected filename, not a path.")

    found = re.search(r"\bcutSegments\s*:\s*\[", raw)
    if not found:
        raise ConversionError("LLC has no cutSegments array.")
    pos, depth, quote_char, escaped = found.end(), 1, None, False
    content_start = pos
    while pos < len(raw) and depth:
        ch = raw[pos]
        if quote_char:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote_char:
                quote_char = None
        else:
            if ch in ("'", '"'):
                quote_char = ch
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
        pos += 1
    if depth:
        raise ConversionError("Unclosed cutSegments array in LLC.")
    selection = raw[content_start:pos - 1]
    blocks = re.findall(r"\{([^{}]*)\}", selection, re.S)
    if not blocks:
        raise ConversionError("No segments found inside cutSegments.")

    segments: list[Segment] = []
    for idx, block in enumerate(blocks, 1):
        selected = re.search(r"\bselected\s*:\s*(true|false)", block, re.I)
        if selected and selected.group(1).lower() == "false":
            continue
        start = re.search(r"\bstart\s*:\s*([0-9]+(?:\.[0-9]+)?)", block)
        end = re.search(r"\bend\s*:\s*([0-9]+(?:\.[0-9]+)?)", block)
        if not (start and end):
            raise ConversionError(f"Segment #{idx} needs explicit start/end. Set both boundaries in LosslessCut.")
        a, b = Decimal(start.group(1)), Decimal(end.group(1))
        if a < 0 or b <= a:
            raise ConversionError(f"Invalid segment #{idx}: {a} - {b} seconds.")
        segments.append(Segment(a, b, _field(block, "name") or ""))
    if not segments:
        raise ConversionError("No selected cuts found in LLC.")
    for idx in range(1, len(segments)):
        if segments[idx].start < segments[idx - 1].end:
            raise ConversionError(f"Cuts overlap or are out of order around segment #{idx + 1}.")
    return filename, segments


def frames(seconds: Decimal, fps: int) -> int:
    return int((seconds * fps).to_integral_value(rounding=ROUND_HALF_UP))


def frame_time(count: int, fps: int) -> str:
    return f"{count}/{fps}s" if count else "0s"


def win_url(path: str | Path) -> str:
    p = PureWindowsPath(str(path))
    if not p.drive or not p.is_absolute():
        raise ConversionError(f"Expected absolute Windows drive path, got: {path}")
    return "file:///" + quote(p.as_posix(), safe="/:")


def probe(path: Path) -> dict:
    """Inspect media without loading or copying it. Requires ffprobe on PATH."""
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=index,codec_type,codec_name,sample_rate,channels", "-of", "json", str(path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise ConversionError("ffprobe not found. Install FFmpeg: winget install --id Gyan.FFmpeg -e; restart terminal.") from exc
    if result.returncode:
        raise ConversionError(f"ffprobe failed for {path}: {result.stderr.strip()}")
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ConversionError(f"Cannot parse ffprobe output for {path}.") from exc
    return parsed


def duration_from_probe(info: dict) -> Decimal:
    value = info.get("format", {}).get("duration")
    if value is None:
        raise ConversionError("ffprobe did not report source duration.")
    return Decimal(str(value))


def _audio_streams(info: dict) -> list[dict]:
    return [stream for stream in info.get("streams", []) if stream.get("codec_type") == "audio"]


def check_audio_output(path: Path, original_duration: Decimal) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        info = probe(path)
        streams = _audio_streams(info)
        return bool(streams) and abs(duration_from_probe(info) - original_duration) <= Decimal("3")
    except (ConversionError, OSError, ValueError):
        return False


def audio_names(recording_id: str) -> tuple[str, str]:
    return f"{recording_id}_Game_Track3.m4a", f"{recording_id}_Mic_Track2.m4a"


def extract_audio(mkv: Path, audio_dir: Path, recording_id: str, info: dict, *, game_index: int, mic_index: int) -> tuple[Path, Path]:
    streams = _audio_streams(info)
    if len(streams) <= max(game_index, mic_index):
        raise ConversionError(
            f"{mkv.name} has {len(streams)} audio streams, but config needs audio indices "
            f"{game_index} (game) and {mic_index} (mic). Check OBS settings for this recording."
        )
    expected_duration = duration_from_probe(info)
    game_name, mic_name = audio_names(recording_id)
    game_file, mic_file = audio_dir / game_name, audio_dir / mic_name
    audio_dir.mkdir(parents=True, exist_ok=True)

    required: list[tuple[int, Path, str]] = []
    for index, path in ((game_index, game_file), (mic_index, mic_file)):
        if check_audio_output(path, expected_duration):
            print(f"[REUSE] {path.name} (already extracted and duration checked)")
            continue
        if path.exists():
            raise ConversionError(f"Existing audio file looks incomplete: {path}. Rename it manually to inspect; not overwriting.")
        codec = str(streams[index].get("codec_name", ""))
        required.append((index, path, codec))
    if not required:
        return game_file, mic_file
    if not shutil.which("ffmpeg"):
        raise ConversionError("ffmpeg not found. Install FFmpeg: winget install --id Gyan.FFmpeg -e; restart terminal.")

    tmp_files: list[tuple[Path, Path]] = []
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning", "-stats", "-i", str(mkv)]
    for index, output, codec in required:
        partial = output.with_name(output.stem + ".partial.m4a")
        if partial.exists():
            raise ConversionError(f"Incomplete temp file exists: {partial}. Inspect/delete it before retrying.")
        cmd += ["-map", f"0:a:{index}", "-vn"]
        if codec == "aac":
            cmd += ["-c:a", "copy"]
        else:
            print(f"[NOTICE] {output.name}: codec {codec} is not AAC; converting audio only to AAC 192k.")
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd += [str(partial)]
        tmp_files.append((partial, output))

    print(f"[AUDIO] Processing {len(required)} stream(s), original MKV is read-only...", flush=True)
    try:
        proc = subprocess.run(cmd, check=False)
        if proc.returncode:
            raise ConversionError(f"ffmpeg exited with code {proc.returncode}; see error above.")
        for tmp, output in tmp_files:
            if not check_audio_output(tmp, expected_duration):
                raise ConversionError(f"Extracted audio did not pass duration/stream check: {tmp}")
        for tmp, output in tmp_files:
            tmp.rename(output)
            print(f"[AUDIO_OK] {output.name}: {output.stat().st_size / (1024*1024):.1f} MiB")
    except Exception:
        for tmp, _ in tmp_files:
            # A failed extraction never creates the final output file.
            tmp.unlink(missing_ok=True)
        raise
    return game_file, mic_file


def generate_xml(
    source_mkv: str | Path,
    game_file: str | Path,
    mic_file: str | Path,
    segments: list[Segment],
    *,
    fps: int = 60,
    width: int = 1920,
    height: int = 1080,
    source_duration: Decimal,
    timeline_name: str = "Minecraft - Separated Game+Mic",
    recording_id: str = "REC01",
) -> tuple[str, dict]:
    """Build same three-asset / nested-audio FCPXML layout as verified REC01.

    Resolve may expose audio contained in the video MKV as A1 (mixed). Mute A1;
    keep separate GAME and MIC tracks audible only after verifying by ear.
    """
    if fps <= 0 or width <= 0 or height <= 0:
        raise ConversionError("fps, width and height must be positive.")
    cuts = [(frames(s.start, fps), frames(s.end, fps)) for s in segments]
    if any(b <= a for a,b in cuts):
        raise ConversionError("One cut rounded to zero frames. Increase its length in LosslessCut.")
    last_frame = max(b for a,b in cuts)
    source_frames = max(last_frame + 1, frames(source_duration, fps))
    total = sum(b - a for a,b in cuts)
    root = Element("fcpxml", {"version": "1.8"})
    resources = SubElement(root, "resources")
    SubElement(resources, "format", {
        "id": "r1", "name": f"FFVideoFormat{height}p{fps}", "frameDuration": f"1/{fps}s",
        "width": str(width), "height": str(height), "colorSpace": "1-1-1 (Rec. 709)",
    })
    SubElement(resources, "asset", {
        "id": "r2", "name": PureWindowsPath(str(source_mkv)).name,
        "src": win_url(source_mkv), "start": "0s", "duration": frame_time(source_frames, fps),
        "hasVideo": "1", "hasAudio": "1", "format": "r1",
    })
    for rid, path in (("r3", game_file), ("r4", mic_file)):
        SubElement(resources, "asset", {
            "id": rid, "name": PureWindowsPath(str(path)).name,
            "src": win_url(path), "start": "0s", "duration": frame_time(source_frames, fps),
            "hasAudio": "1", "audioSources": "1", "audioChannels": "2", "audioRate": "48000",
        })
    library = SubElement(root, "library")
    event = SubElement(library, "event", {"name": "Minecraft 100 Days - Selected Gameplay"})
    project = SubElement(event, "project", {"name": timeline_name})
    sequence = SubElement(project, "sequence", {
        "format": "r1", "duration": frame_time(total, fps),
        "tcStart": "0s", "tcFormat": "NDF", "audioLayout": "stereo", "audioRate": "48k",
    })
    spine = SubElement(sequence, "spine")
    timeline_offset = 0
    for idx, (a,b) in enumerate(cuts, 1):
        dur = b - a
        video = SubElement(spine, "asset-clip", {
            "ref": "r2", "name": f"{recording_id}_S{idx:03d}_VIDEO",
            "offset": frame_time(timeline_offset, fps), "start": frame_time(a, fps),
            "duration": frame_time(dur, fps), "srcEnable": "video",
        })
        # Connected audio anchored in source-relative parent space, validated in REC01.
        for rid, lane, name, role in (("r3", "-1", "GAME", "effects"), ("r4", "-2", "MIC", "dialogue")):
            SubElement(video, "asset-clip", {
                "ref": rid, "name": f"{recording_id}_S{idx:03d}_{name}",
                "lane": lane, "offset": frame_time(a, fps), "start": frame_time(a, fps),
                "duration": frame_time(dur, fps), "srcEnable": "audio", "audioRole": role,
            })
        timeline_offset += dur
    indent(root, space="  ")
    document = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + tostring(root, encoding="unicode") + "\n"
    return document, {"clip_count":len(cuts), "total_frames":total, "total_seconds":total / fps, "source_uri":win_url(source_mkv)}


def save_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".writing")
    try:
        pending.write_text(text, encoding="utf-8")
        pending.replace(path)
    except Exception:
        pending.unlink(missing_ok=True)
        raise
