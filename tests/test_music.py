"""Tests for the claume music player (claume/music.py)."""
from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from claume import music


def _make_library(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, freq in (
        ("01 - Alpha Wave.wav", 440),
        ("02 - Beta Storm.wav", 550),
        ("03 - Gamma Rain.wav", 660),
    ):
        with wave.open(str(folder / name), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(
                b"".join(
                    struct.pack("<h", int(6000 * math.sin(2 * math.pi * freq * i / 8000)))
                    for i in range(8000)
                )
            )
    # a non-audio file that must be ignored by the scanner
    (folder / "notes.txt").write_text("not music")
    return folder


class TestScanAndDisplay(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.lib = _make_library(self.tmp / "lib")

    def test_scan_folder_finds_only_audio(self) -> None:
        tracks = music.scan_folder(self.lib)
        names = [t.name for t in tracks]
        self.assertEqual(len(tracks), 3)
        self.assertNotIn("notes.txt", " ".join(names))

    def test_scan_missing_folder_is_empty(self) -> None:
        self.assertEqual(music.scan_folder(self.tmp / "nope"), [])

    def test_display_name_strips_track_numbers(self) -> None:
        p = self.lib / "01 - Alpha Wave.wav"
        self.assertEqual(music._display_name(p), "Alpha Wave")


class TestPlayer(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.lib = _make_library(self.tmp / "lib")
        self.player = music.MusicPlayer()
        self.player.load_folder(self.lib)

    def test_load_folder(self) -> None:
        self.assertEqual(len(self.player.tracks), 3)

    def test_volume_clamps(self) -> None:
        self.assertEqual(self.player.set_volume(150), 100)
        self.assertEqual(self.player.set_volume(-5), 0)
        self.assertEqual(self.player.set_volume(55), 55)

    def test_shuffle_and_loop_toggles(self) -> None:
        self.assertTrue(self.player.toggle_shuffle())  # was off -> on
        self.assertFalse(self.player.toggle_shuffle())
        self.assertEqual(self.player.loop, "all")
        self.assertEqual(self.player.cycle_loop(), "one")
        self.assertEqual(self.player.cycle_loop(), "off")
        self.assertEqual(self.player.cycle_loop(), "all")

    def test_next_without_backend_is_safe(self) -> None:
        # No backend configured (or present) — next() must not raise.
        self.player.backend = None
        self.assertIsNone(self.player.next())

    def test_play_match_advances(self) -> None:
        if self.player.backend is None:
            self.skipTest("no audio backend on this machine")
        t = self.player.play_match("gamma")
        self.assertIsNotNone(t)
        self.assertIn("Gamma", t.name)
        status = self.player.status()
        self.assertEqual(status["index"], 3)
        self.player.stop()

    def test_play_index_transport(self) -> None:
        if self.player.backend is None:
            self.skipTest("no audio backend on this machine")
        import time as _time

        t = self.player.play_index(0)
        self.assertIn("Alpha", t.name)
        _time.sleep(0.6)
        s = self.player.status()
        self.assertTrue(s["playing"])
        self.player.pause()
        self.assertTrue(self.player.status()["paused"])
        self.player.resume()
        self.assertFalse(self.player.status()["paused"])
        self.player.stop()
        self.assertFalse(self.player.status()["playing"])


class TestVoiceIntents(unittest.TestCase):
    def test_play_intents(self) -> None:
        self.assertEqual(music.music_intent("play some music"), "play")
        self.assertEqual(music.music_intent("jarvis play music"), "play")
        self.assertEqual(music.music_intent("Music"), "play")
        self.assertEqual(music.music_intent("put on my playlist"), "play")

    def test_named_track_intent(self) -> None:
        self.assertEqual(music.music_intent("play beta storm"), "play beta storm")

    def test_transport_intents(self) -> None:
        self.assertEqual(music.music_intent("pause the music"), "pause")
        self.assertEqual(music.music_intent("resume the music"), "resume")
        self.assertEqual(music.music_intent("stop music"), "stop")
        self.assertEqual(music.music_intent("next track"), "next")
        self.assertEqual(music.music_intent("skip"), "next")
        self.assertEqual(music.music_intent("previous song"), "prev")

    def test_state_intents(self) -> None:
        self.assertEqual(music.music_intent("what song is this"), "what")
        self.assertEqual(music.music_intent("shuffle on"), "shuffle")
        self.assertEqual(music.music_intent("loop"), "loop")
        self.assertEqual(music.music_intent("set volume to 40"), "volume 40")
        self.assertEqual(music.music_intent("louder"), "louder")
        self.assertEqual(music.music_intent("quiet"), "quiet")

    def test_non_music_is_none(self) -> None:
        self.assertIsNone(music.music_intent("what is the weather tomorrow"))
        self.assertIsNone(music.music_intent(""))
        self.assertIsNone(music.music_intent("open the pod bay doors"))


if __name__ == "__main__":
    unittest.main()
