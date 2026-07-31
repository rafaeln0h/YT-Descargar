import json
import tempfile
import unittest
from pathlib import Path

from ymd.metadata import (
    apply_metadata_defaults,
    merge_ytdlp_metadata,
    normalize_metadata,
    write_lyrics,
)


class MetadataTests(unittest.TestCase):
    def test_defaults_do_not_override_detected_values(self):
        result = apply_metadata_defaults(
            {"title": "Song", "artist": "Artist", "composer": "Detected"},
            {"composer": "Default", "language": "es", "bpm": "120"},
            source_url="https://www.youtube.com/watch?v=abc",
        )
        self.assertEqual(result["composer"], "Detected")
        self.assertEqual(result["language"], "es")
        self.assertEqual(result["bpm"], 120)
        self.assertEqual(result["source_url"], "https://www.youtube.com/watch?v=abc")

    def test_normalizes_boolean_and_numeric_fields(self):
        result = normalize_metadata(
            {
                "track": "3",
                "track_total": "12",
                "disc": "x",
                "explicit": "yes",
                "compilation": "false",
            }
        )
        self.assertEqual(result["track"], 3)
        self.assertEqual(result["track_total"], 12)
        self.assertEqual(result["disc"], "")
        self.assertTrue(result["explicit"])
        self.assertFalse(result["compilation"])

    def test_merges_public_ytdlp_metadata_and_omits_stream_url(self):
        result = merge_ytdlp_metadata(
            {"title": "Song", "artist": "Unknown", "album": "Unknown"},
            {
                "id": "abc123",
                "title": "Song",
                "artist": "Detected Artist",
                "album": "Detected Album",
                "webpage_url": "https://www.youtube.com/watch?v=abc123",
                "url": "https://signed.example/private-token",
                "chapters": [{"title": "Intro", "start_time": 0}],
                "requested_downloads": [{"format_id": "251", "acodec": "opus"}],
            },
        )
        self.assertEqual(result["youtube_id"], "abc123")
        self.assertEqual(result["artist"], "Detected Artist")
        self.assertEqual(result["format_id"], "251")
        self.assertNotIn("private-token", json.dumps(result))

    def test_embeds_lyrics_in_mp3(self):
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder) / "song.mp3"
            media.write_bytes(b"")
            self.assertTrue(
                write_lyrics(
                    media,
                    "Primera línea\nSegunda línea",
                    language="spa",
                    source="lrclib",
                    source_id="123",
                )
            )

            from mutagen.id3 import ID3

            frames = ID3(media).getall("USLT")
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0].lang, "spa")
            self.assertEqual(frames[0].text, "Primera línea\nSegunda línea")
            custom = {frame.desc: str(frame.text[0]) for frame in ID3(media).getall("TXXX")}
            self.assertEqual(custom["LYRICS_SOURCE"], "lrclib")
            self.assertEqual(custom["LYRICS_SOURCE_ID"], "123")


if __name__ == "__main__":
    unittest.main()
