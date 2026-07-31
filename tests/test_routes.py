import tempfile
import unittest
from pathlib import Path

from flask import Flask

from ymd.library import encode_media_id
from ymd.routes import create_services_blueprint


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.media = self.root / "sample.mp3"
        self.media.write_bytes(b"0123456789")
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
        self.assertEqual(response.get_json()["count"], 1)

        media_id = encode_media_id("sample.mp3")
        response = self.client.get(
            f"/api/library/media/{media_id}",
            headers={"Range": "bytes=0-3"},
        )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.data, b"0123")
        response.close()

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


if __name__ == "__main__":
    unittest.main()
