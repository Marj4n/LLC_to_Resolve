"""Local tests that never read or modify actual DaVinci installations."""
from __future__ import annotations

import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from converter import ConversionError, Segment, audio_names, frames, generate_xml, parse_llc, win_url


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "recording01.llc"


class ConversionTests(unittest.TestCase):
    def test_fixture_67_cuts_and_duration_matches_resolve(self):
        name, cuts = parse_llc(FIXTURE)
        self.assertEqual(name, "2026-10-11 23-02-42.mkv")
        self.assertEqual(len(cuts), 67)
        xml, stats = generate_xml(
            r"D:\record\2026-10-11 23-02-42.mkv",
            r"C:\Development\Minecraft 100 Days - Vampire\02 - Selected Clips\Audio Extracts\REC01_Game_Track3.m4a",
            r"C:\Development\Minecraft 100 Days - Vampire\02 - Selected Clips\Audio Extracts\REC01_Mic_Track2.m4a",
            cuts, source_duration=Decimal("8032"), recording_id="REC01",
        )
        self.assertEqual(stats["total_frames"], 345730)
        self.assertEqual(stats["clip_count"], 67)
        root = ET.fromstring(xml)
        self.assertEqual(len(root.findall(".//spine/asset-clip")), 67)
        self.assertEqual(len(root.findall(".//spine/asset-clip/asset-clip")), 134)
        self.assertEqual(root.find(".//sequence").attrib["duration"], "345730/60s")
        self.assertEqual(root.find(".//spine/asset-clip").attrib["start"], "838/60s")
        self.assertEqual(root.find(".//spine/asset-clip").attrib["duration"], "7952/60s")
        resources = root.find("resources")
        assets = resources.findall("asset")
        self.assertEqual(len(assets), 3)
        self.assertIn("file:///D:/record/", assets[0].attrib["src"])
        self.assertIn("%20", assets[0].attrib["src"])

    def test_windows_url(self):
        self.assertEqual(win_url(r"D:\record\a b#c.mkv"), "file:///D:/record/a%20b%23c.mkv")
        with self.assertRaises(ConversionError):
            win_url("relative.mkv")

    def test_llc_skips_unselected_and_checks_order(self):
        raw = """{version:2,mediaFileName:'one.mkv',cutSegments:[
        {start:1.2,end:2.3,selected:true,name:'Found diamonds'},
        {start:3.1,end:4.2,selected:false},
        {start:5,end:6,selected:true},] }"""
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"test.llc";p.write_text(raw,encoding="utf-8")
            source,segs=parse_llc(p)
            self.assertEqual(source,"one.mkv")
            self.assertEqual(len(segs),2)
            self.assertEqual(segs[0].name,"Found diamonds")
            p.write_text(raw.replace("start:5,end:6","start:2,end:6"),encoding="utf-8")
            with self.assertRaises(ConversionError): parse_llc(p)

    def test_rounded_to_zero_frames_is_rejected(self):
        with self.assertRaises(ConversionError):
            generate_xml(r"D:\record\x.mkv",r"C:\x.m4a",r"C:\y.m4a",
                         [Segment(Decimal("1.0001"),Decimal("1.0002"))],
                         source_duration=Decimal(9))

    def test_audio_names_stable(self):
        self.assertEqual(audio_names("REC02"),("REC02_Game_Track3.m4a","REC02_Mic_Track2.m4a"))

if __name__ == "__main__":
    unittest.main()
