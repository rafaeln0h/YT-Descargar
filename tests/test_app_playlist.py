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


class DownloadHistoryRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_history_file = app_playlist.HISTORY_FILE
        self.original_queue = app_playlist.DOWNLOAD_QUEUE
        app_playlist.HISTORY_FILE = Path(self.temp.name) / "history.json"
        app_playlist.DOWNLOAD_QUEUE = {}
        self.client = app_playlist.app.test_client()

    def tearDown(self):
        app_playlist.HISTORY_FILE = self.original_history_file
        app_playlist.DOWNLOAD_QUEUE = self.original_queue
        self.temp.cleanup()

    def test_history_endpoint_marks_download_without_worker_as_interrupted(self):
        app_playlist.save_history([{
            "history_id": "h-stale",
            "queue_id": 7,
            "status": "descargando",
            "progress": 42,
            "speed": "3.11MiB/s",
            "eta": "00:00",
            "updated_at": "2000-01-01T00:00:00",
            "request_payload": {"url": "https://music.youtube.com/watch?v=abcdefghijk"},
        }])

        response = self.client.get("/api/history")

        self.assertEqual(response.status_code, 200)
        recovered = response.get_json()[0]
        self.assertEqual(recovered["status"], "interrumpido")
        self.assertEqual(recovered["progress"], 42)
        self.assertEqual(recovered["speed"], "")
        self.assertEqual(recovered["eta"], "")
        self.assertIn("archivos descargados se conservan", recovered["note"])
        self.assertEqual(app_playlist.load_history()[0]["status"], "interrumpido")

        interrupted_at = recovered["interrupted_at"]
        second_read = self.client.get("/api/history").get_json()[0]
        self.assertEqual(second_read["interrupted_at"], interrupted_at)

    def test_history_endpoint_keeps_entry_with_active_worker(self):
        app_playlist.save_history([{
            "history_id": "h-active",
            "queue_id": 8,
            "status": "descargando",
            "progress": 25,
            "updated_at": "2000-01-01T00:00:00",
        }])
        app_playlist.DOWNLOAD_QUEUE[8] = {
            "queue_id": 8,
            "history_id": "h-active",
            "status": "descargando",
        }

        active = self.client.get("/api/history").get_json()[0]

        self.assertEqual(active["status"], "descargando")
        self.assertEqual(active["progress"], 25)

    def test_validation_counts_recorded_files_across_album_folders(self):
        album_one = Path(self.temp.name) / "artist" / "album-one"
        album_two = Path(self.temp.name) / "artist" / "album-two"
        album_one.mkdir(parents=True)
        album_two.mkdir(parents=True)
        first = album_one / "01 song.mp3"
        second = album_two / "01 other.mp3"
        unrelated = Path(self.temp.name) / "unrelated.mp3"
        first.write_bytes(b"audio")
        second.write_bytes(b"audio")
        unrelated.write_bytes(b"audio")
        app_playlist.save_history([{
            "history_id": "h-multi-album",
            "kind": "playlist",
            "status": "interrumpido",
            "destination": self.temp.name,
            "total_items": 2,
            "media_files": [str(first), str(second)],
        }])

        payload = self.client.post("/api/history/h-multi-album/validate").get_json()

        self.assertEqual(payload["media_files_found"], 2)
        self.assertEqual(payload["recorded_files_found"], 2)
        self.assertEqual(payload["destination_files_found"], 3)
        self.assertTrue(payload["looks_complete"])

    def test_playlist_retry_preserves_expanded_total_until_worker_recounts(self):
        app_playlist.save_history([{
            "history_id": "h-retry-total",
            "kind": "playlist",
            "status": "interrumpido",
            "created_at": "2026-01-01T00:00:00",
            "total_items": 109,
            "request_payload": {"url": "https://music.youtube.com/playlist?list=test"},
        }])
        data = {
            "url": "https://music.youtube.com/playlist?list=test",
            "artist": "Artist",
            "album": "Discography",
            "reuse_history_id": "h-retry-total",
            "selected_items": [
                {"url": "https://music.youtube.com/playlist?list=album-one"},
                {"url": "https://music.youtube.com/playlist?list=album-two"},
            ],
        }

        with patch.object(app_playlist.threading.Thread, "start"):
            app_playlist.start_playlist_download(data)

        retried = app_playlist.load_history()[0]
        self.assertEqual(retried["total_items"], 109)
        self.assertEqual(retried["created_at"], "2026-01-01T00:00:00")
        self.assertEqual(retried["retry_count"], 1)
        self.assertIn("retry_started_at", retried)

    def test_finished_progress_hook_clears_stale_speed_and_eta(self):
        app_playlist.save_history([{
            "history_id": "h-finished-hook",
            "status": "descargando",
            "updated_at": "2000-01-01T00:00:00",
        }])
        app_playlist.DOWNLOAD_QUEUE[9] = {
            "queue_id": 9,
            "history_id": "h-finished-hook",
            "status": "descargando",
            "progress": 80,
            "speed": "2MiB/s",
            "eta": "00:00",
        }

        app_playlist.update_progress(9, {"status": "finished"}, is_playlist=True, current=2, total=3)

        queue = app_playlist.DOWNLOAD_QUEUE[9]
        self.assertEqual(queue["phase"], "procesando")
        self.assertEqual(queue["speed"], "")
        self.assertEqual(queue["eta"], "")
        stored = app_playlist.load_history()[0]
        self.assertEqual(stored["phase"], "procesando")
        self.assertEqual(stored["eta"], "")


class PlaylistOrganizationTests(unittest.TestCase):
    def test_channel_section_links_are_not_misclassified_as_songs(self):
        self.assertEqual(
            app_playlist.classify_entry_type("https://www.youtube.com/@LillyGoodmanOficial/videos"),
            "artist",
        )
        parsed = app_playlist.parse_entries(
            [{"title": "Lilly Goodman - Videos", "url": "https://www.youtube.com/@LillyGoodmanOficial/videos"}],
            default_artist="Lilly Goodman",
        )
        self.assertEqual(parsed, [])

    def test_catalog_summary_separates_release_types(self):
        summary = app_playlist.summarize_catalog([
            {"item_type": "collection", "category": "album"},
            {"item_type": "collection", "category": "single"},
            {"item_type": "collection", "category": "ep"},
            {"item_type": "collection", "category": "playlist"},
            {"item_type": "song", "category": "video"},
        ])
        self.assertEqual(summary["album"], 1)
        self.assertEqual(summary["single"], 1)
        self.assertEqual(summary["ep"], 1)
        self.assertEqual(summary["playlist"], 1)
        self.assertEqual(summary["video"], 1)

    def test_expanding_catalog_release_preserves_artist_year_and_release_type(self):
        release = {
            "title": "Soy Sana",
            "artist": "Lilly Goodman",
            "album_artist": "Lilly Goodman",
            "year": "2024",
            "release_type": "EP",
            "category": "ep",
            "item_type": "collection",
            "url": "https://music.youtube.com/playlist?list=OLAK5uy_ep",
        }
        playlist_info = {
            "title": "Soy Sana",
            "uploader": "Lilly Goodman - Topic",
            "entries": [{"title": "Tema", "url": "abcdefghijk", "track_number": 1}],
        }
        with patch.object(app_playlist, "extract_url_info", return_value=playlist_info):
            expanded = app_playlist.expand_download_items([release])
        self.assertEqual(len(expanded), 1)
        self.assertEqual(expanded[0]["album_artist"], "Lilly Goodman")
        self.assertEqual(expanded[0]["year"], "2024")
        self.assertEqual(expanded[0]["release_type"], "EP")
        self.assertEqual(expanded[0]["collection_kind"], "official_album")

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

    def test_single_release_groups_in_one_artist_folder_by_default(self):
        with tempfile.TemporaryDirectory() as folder:
            config = {**app_playlist.DEFAULT_CONFIG, "download_path": folder}
            output, filename = app_playlist.build_output_paths(
                {
                    "title": "Cancion Uno",
                    "artist": "Artista",
                    "album": "Cancion Uno",
                    "album_artist": "Artista",
                    "year": "2026",
                    "track": 1,
                    "playlist_track": 1,
                    "is_playlist_item": True,
                    "collection_kind": "official_album",
                    "release_type": "Single",
                },
                config,
            )
        self.assertTrue(str(output).endswith(str(Path("Artista") / "Singles")))
        self.assertEqual(filename, "01 - Cancion Uno")

    def test_single_release_can_group_by_year_without_changing_eps(self):
        with tempfile.TemporaryDirectory() as folder:
            config = {
                **app_playlist.DEFAULT_CONFIG,
                "download_path": folder,
                "single_folder_mode": "by_artist_year",
            }
            base = {
                "title": "Tema",
                "artist": "Artista",
                "album_artist": "Artista",
                "album": "Lanzamiento",
                "year": "2024",
                "track": 1,
                "playlist_track": 1,
                "is_playlist_item": True,
                "collection_kind": "official_album",
            }
            single_output, _ = app_playlist.build_output_paths(
                {**base, "release_type": "Sencillo"},
                config,
            )
            ep_output, _ = app_playlist.build_output_paths(
                {**base, "release_type": "EP"},
                config,
            )
        self.assertTrue(str(single_output).endswith(str(Path("Artista") / "Singles" / "2024")))
        self.assertTrue(str(ep_output).endswith(str(Path("Artista") / "2024 - Lanzamiento")))

    def test_download_pages_expose_single_folder_controls(self):
        client = app_playlist.app.test_client()
        self.assertIn('id="singleFolderMode"', client.get("/").get_data(as_text=True))
        self.assertIn('id="singleFolderTemplate"', client.get("/settings").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
