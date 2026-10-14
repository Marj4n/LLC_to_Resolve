# Marj4n LLC to Resolve

**LosslessCut `.llc` → DaVinci Resolve FCPXML, with separate game audio and microphone.**

Made for **Minecraft 100 Days - Vampire / Smooth Odyssey** on Windows. Uses the exact nested-audio FCPXML structure already confirmed working with **DaVinci Resolve Studio 21** for recording #01.

The original gameplay `.mkv` is referenced directly from `D:\record`. **Gameplay is not copied, trimmed or re-encoded.** Game and mic audio are extracted into much smaller `.m4a` files, losslessly remuxed if AAC, and referenced by the timeline XML.

## Setup (once)

1. Install Python 3.11 or newer: `winget install Python.Python.3.13`
2. Install FFmpeg, including ffprobe: `winget install --id Gyan.FFmpeg -e`
3. Restart PowerShell and check `py -3 --version`, `ffmpeg -version`, `ffprobe -version`.
4. Extract this ZIP to any folder, e.g. `C:\Development\Minecraft 100 Days - Vampire\07 - Tools\Marj4n LLC to Resolve`.
5. Open `config.json` to review paths and OBS audio routing. The default paths already match the shared setup.

No `pip install` is required. No project has to be uploaded to ChatGPT for conversion.

## Every recording (recommended)

1. Open the next raw `D:\record\....mkv` in LosslessCut.
2. Select important cuts and **File → Export project (LLC)**. Save the `.llc` into `C:\Development\Minecraft 100 Days - Vampire\05 - DaVinci Project`.
3. **Drag the `.llc` file onto `Start_Converter.bat`**. Alternatively double-click the batch file and use the file-picker.
4. Wait for the audio-only extraction, then the tool generates two timelines in `05 - DaVinci Project\Generated Timelines\RECxx_<filename>\`:
   - `*_TEST_3_Cuts.fcpxml`: 3 cuts for quick validation.
   - `*_FULL_Cuts.fcpxml`: all selected cuts.
5. In Resolve: **File → Import → Timeline**, import test first. Turn on **Automatically import source clips into media pool**. Check video, audio, and synchronization.
6. Import the full version once the test works. Save the project with `Ctrl+S`.

The tool automatically assigns `REC01`, `REC02`, ... from the original MKV filenames sorted chronologically in `D:\record`. Do not rename original files after choosing cuts.

## Batch mode

Put `.llc` projects directly in the configured `llc_dir` and double-click `Convert_All_LLC.bat`. It will process all projects in that folder, continue past individual failures, and reuse previously validated audio extractions.

## Audio routing

As shown in the user's OBS Advanced Audio Properties (verify that this was also used for each particular recording):

| OBS stream | Content | ffmpeg input index |
| --- | --- | --- |
| 1 | Combined game + microphone | `0:a:0` (not extracted) |
| 2 | Microphone only | `0:a:1` |
| 3 | Game Capture only | `0:a:2` |

The converter defaults to **Game = 2**, **Mic = 1** in zero-based FFmpeg audio indexes.

**Important:** Resolve may still add the source MKV's combined audio as an extra A1 track, as it did in the successfully tested recording #01 timeline. **Mute that combined A1 track** and leave the independently extracted **GAME + MIC tracks enabled** (verify which is which by muting one at a time). Do not leave mic muted if you want live reactions.

The tool avoids duplicating original video, but audio files do consume disk space (normally hundreds of MB rather than tens of GB for long recordings). The output folder should have room for the audio extraction.

## Advanced CLI

```powershell
cd "C:\path\to\Marj4n LLC to Resolve"
py -3 .\main.py --llc "C:\Development\Minecraft 100 Days - Vampire\05 - DaVinci Project\02_Second_Recording.llc"
py -3 .\main.py --all
py -3 .\main.py --llc "C:\path\to\01_First_Recording.llc" --xml-only
py -3 -m unittest discover -s tests -v
```

`--xml-only` is for cases where valid audio extractions already exist. `--test-count 5` changes the number of clips in the test timeline.

## Checks and limitations

- The parser supports standard LosslessCut JSON5-like `.llc` projects with explicit start/end, ordered non-overlapping selections. It skips `selected:false` cuts and rejects invalid/ambiguous ranges.
- The FCPXML uses **60 fps / 1920×1080** unless `config.json` is changed. Cuts round to the nearest frame; as with the previously tested XML, verify joins and audio sync in Resolve.
- The converter expects at least 3 audio streams and the OBS routing above. If an individual recording differs, change indexes in `config.json` **after checking that video's streams**. Otherwise the converter stops instead of silently mixing wrong tracks.
- AAC audio is remuxed using `-c:a copy`; other input codecs are encoded to AAC 192 kbps for `.m4a` compatibility, which is audio-only and does not re-encode the video.
- Output names include the original filename to prevent two recordings from overwriting each other. Existing audio is only reused if its duration and format can be checked; invalid files are not overwritten silently.
- Editing an existing LLC and regenerating XML does **not** automatically update an existing imported Resolve timeline. Import a newly generated XML as a new timeline; do not delete your existing edit.
- The tool does **not** automatically generate a 100 Days master timeline from 22 separately selected recordings, nor does it determine gameplay day numbers or story highlights. Those belong to the creative edit.
- Keep the raw `.mkv`, exported `.llc`, and finished Resolve project safe. An LLC or XML is not a substitute for raw footage. Do not delete raw files just because the timeline imports.

## Troubleshooting

- `ffmpeg` or `ffprobe` missing: install FFmpeg and restart the terminal.
- `Missing raw MKV`: check `mediaFileName` in your `.llc` and `source_dir` in `config.json`.
- `No audio stream #2`: check that OBS actually recorded three audio streams in that file. Do not assume every OBS recording is identical.
- `Existing audio file looks incomplete`: inspect the named `.m4a` file; the converter refuses to overwrite a suspect one.
- `Media Offline` in Resolve: ensure the original MKV and generated M4A files remain in their original paths, then relink media if necessary.
- A1/A2/A3 are not in the desired order: inspect which track plays when others are muted, rather than assuming track numbers have fixed roles across XML imports.

## Test status

- 67-cut fixture parses and exactly matches the previously confirmed **345,730 frames / 5,762.1667 seconds** timeline.
- XML serialization and selected track layout are unit tested.
- The earlier equivalent layout has been successfully imported into the user's DaVinci Resolve Studio 21.
- **This specific new automation hasn't yet been run on the user's Windows PC.** Test with recording #01 or #02 and verify its exported XML first.

Author: Marj4n project utility.
