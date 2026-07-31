import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_playlist


class PersistentBatchQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_file = app_playlist.BATCH_FILE
        self.original_jobs = app_playlist.BATCH_JOBS
        self.original_loaded = app_playlist.BATCH_LOADED
        app_playlist.BATCH_FILE = Path(self.temp.name) / "batch.json"
        app_playlist.BATCH_JOBS = []
        app_playlist.BATCH_LOADED = True
        self.client = app_playlist.app.test_client()

    def tearDown(self):
        app_playlist.BATCH_FILE = self.original_file
        app_playlist.BATCH_JOBS = self.original_jobs
        app_playlist.BATCH_LOADED = self.original_loaded
        self.temp.cleanup()

    def test_batch_endpoint_persists_and_deduplicates_jobs(self):
        job = {
            "kind": "playlist",
            "label": "Album de prueba",
            "payload": {
                "url": "https://music.youtube.com/playlist?list=OLAK5uy_test",
                "selected_items": [{"url": "https://music.youtube.com/watch?v=abcdefghijk"}],
            },
        }
        with patch.object(app_playlist, "ensure_batch_dispatcher"):
            response = self.client.post("/api/batch-queue", json={"jobs": [job, job]})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["created"], 1)
        self.assertEqual(payload["duplicates"], 1)
        self.assertTrue(app_playlist.BATCH_FILE.exists())

        with patch.object(app_playlist, "ensure_batch_dispatcher"):
            listed = self.client.get("/api/batch-queue").get_json()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["status"], "pending")
        self.assertNotIn("payload", listed[0])


class PlaylistOrganizationTests(unittest.TestCase):
    def test_removed_suite_route_returns_not_found(self):
        self.assertEqual(app_playlist.app.test_client().get("/suite").status_code, 404)

    def test_smart_playlist_uses_playlist_folder_and_hyphenated_position(self):
        with tempfile.TemporaryDirectory() as folder:
            config = {
                **app_playlist.DEFAULT_CONFIG,
                "download_path": folder,
                "playlist_folder_mode": "smart",
            }
            output, filename = app_playlist.build_output_paths(
                {
                    "title": "Nombre de cancion",
                    "artist": "Artista",
                    "album": "Album real",
                    "album_artist": "Artista",
                    "year": "2020",
                    "track": 4,
                    "playlist_track": 2,
                    "playlist_title": "Mi playlist",
                    "is_playlist_item": True,
                    "collection_kind": "playlist",
                },
                config,
            )
        self.assertTrue(str(output).endswith(str(Path("Playlists") / "Mi playlist")))
        self.assertEqual(filename, "02 - Nombre de cancion")

    def test_metadata_repair_status_endpoint_is_connected(self):
        response = app_playlist.app.test_client().get("/api/maintenance/repair-metadata")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("status", payload)
        self.assertIn("summary", payload)

    def test_automatic_enrichment_records_unavailable_sources(self):
        config = {
            **app_playlist.DEFAULT_CONFIG,
            "metadata_sources": [],
        }
        result = app_playlist.apply_automatic_metadata_enrichment(
            {"title": "Tema", "artist": "Artista", "album": "Album"},
            config,
        )
        self.assertEqual(result["enrichment_status"], "partial")
        self.assertIn("genre", result["metadata_missing"])

    def test_smart_official_album_keeps_album_library_structure(self):
        with tempfile.TemporaryDirectory() as folder:
            config = {
                **app_playlist.DEFAULT_CONFIG,
                "download_path": folder,
                "playlist_folder_mode": "smart",
            }
            output, filename = app_playlist.build_output_paths(
                {
                    "title": "Rompiendo Los Limites (Intro)",
                    "artist": "Triple Seven",
                    "album": "Rompiendo Los Limites",
                    "album_artist": "Triple Seven",
                    "year": "2005",
                    "track": 1,
                    "playlist_track": 1,
                    "playlist_title": "Rompiendo Los Limites",
                    "is_playlist_item": True,
                    "collection_kind": "official_album",
                },
                config,
            )
        self.assertTrue(
            str(output).endswith(str(Path("Triple Seven") / "2005 - Rompiendo Los Limites"))
        )
        self.assertEqual(filename, "01 - Rompiendo Los Limites (Intro)")


if __name__ == "__main__":
    unittest.main()
