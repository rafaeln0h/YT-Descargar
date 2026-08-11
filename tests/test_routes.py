import tempfile
import unittest
import wave
from pathlib import Path

from flask import Flask
from mutagen.id3 import APIC, TIT2, TXXX, USLT
from mutagen.wave import WAVE

from ymd.library import encode_media_id
from ymd.routes import create_services_blueprint


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.media = self.root / "sample.mp3"
        self.media.write_bytes(b"0123456789")
        self.tagged = self.root / "tagged.wav"
        with wave.open(str(self.tagged), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b"\x00\x00" * 800)
        tagged = WAVE(self.tagged)
        tagged.add_tags()
        tagged.tags.add(TIT2(encoding=3, text=["Canción con extras"]))
        tagged.tags.add(TXXX(encoding=3, desc="PLAYLIST_TITLE", text=["Favoritas"]))
        tagged.tags.add(USLT(encoding=3, lang="spa", desc="Lyrics", text="Primera línea"))
        tagged.tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Front Cover", data=b"fake-jpeg-cover"))
        tagged.save()
        self.log = self.root / "ymd.log"
        self.log.write_text("line one\nline two\n", encoding="utf-8")
        app = Flask(__name__)
        app.register_blueprint(
            create_services_blueprint(
                lambda: {"download_path": str(self.root), "library_scan_limit": 20},
                log_path=self.log,
            )
        )
        self.client = app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_library_and_range_stream(self):
        response = self.client.get("/api/library")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 2)
        self.assertIn("artists", payload)
        self.assertEqual(payload["summary"]["playlists"], 1)

        media_id = encode_media_id("sample.mp3")
        response = self.client.get(
            f"/api/library/media/{media_id}",
            headers={"Range": "bytes=0-3"},
        )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.data, b"0123")
        response.close()

    def test_artwork_lyrics_and_rescan_endpoints(self):
        media_id = encode_media_id("tagged.wav")
        artwork = self.client.get(f"/api/library/artwork/{media_id}")
        self.assertEqual(artwork.status_code, 200)
        self.assertEqual(artwork.data, b"fake-jpeg-cover")
        artwork.close()

        lyrics = self.client.get(f"/api/library/lyrics/{media_id}")
        self.assertEqual(lyrics.status_code, 200)
        self.assertEqual(lyrics.get_json()["lyrics"], "Primera línea")

        self.tagged.unlink()
        rescan = self.client.post("/api/library/rescan")
        self.assertEqual(rescan.status_code, 200)
        self.assertEqual(rescan.get_json()["count"], 1)

    def test_logs_are_bounded(self):
        response = self.client.get("/api/system/logs?limit=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["lines"], ["line two"])

    def test_capabilities_expose_release_and_metadata_support(self):
        response = self.client.get("/api/system/capabilities")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["version"], "0.012")
        self.assertTrue(payload["features"]["extended_metadata"])
        self.assertIn("musicbrainz", payload["metadata_sources"])
        self.assertEqual(payload["lyrics_sources"], ["youtube_captions", "lrclib"])
        self.assertFalse(payload["features"]["metadata_sidecar"])
        self.assertIn("yt_dlp", payload["runtime"])
        self.assertIn("javascript", payload["runtime"])


if __name__ == "__main__":
    unittest.main()
