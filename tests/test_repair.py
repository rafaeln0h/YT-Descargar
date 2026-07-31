import json
import tempfile
import unittest
from pathlib import Path

from mutagen.id3 import ID3, TALB, TDRC, TIT2, TPE1, TPE2, TRCK

from ymd.repair import (
    build_repair_plan,
    destination_for_metadata,
    prepare_metadata,
    repair_library,
    rollback_library_repair,
    safe_component,
)


def write_test_mp3(path: Path, **values: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tags = ID3()
    mapping = {
        "title": TIT2,
        "artist": TPE1,
        "album": TALB,
        "album_artist": TPE2,
        "year": TDRC,
        "track": TRCK,
    }
    for key, frame in mapping.items():
        if values.get(key):
            tags.add(frame(encoding=3, text=[values[key]]))
    tags.save(path, v2_version=4)


class RepairLibraryTests(unittest.TestCase):
    def test_safe_component_replaces_windows_reserved_characters(self):
        self.assertEqual(safe_component('Album: Uno?* '), "Album_ Uno_")
        self.assertEqual(safe_component("CON"), "_CON")

    def test_destination_uses_embedded_album_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            destination, missing = destination_for_metadata(
                root,
                {
                    "album_artist": "Triple Seven",
                    "year": "2005-01-01",
                    "album": "Rompiendo Los Limites",
                    "track": "1/15",
                    "title": "Intro",
                },
                ".mp3",
            )
            self.assertEqual(missing, [])
            self.assertEqual(
                destination.relative_to(root).as_posix(),
                "Triple Seven/2005 - Rompiendo Los Limites/01 - Intro.mp3",
            )

    def test_dry_run_writes_journal_but_does_not_move_media(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "entrada" / "song.mp3"
            write_test_mp3(
                source,
                title="Intro",
                artist="Triple Seven",
                album_artist="Triple Seven",
                album="Rompiendo Los Limites",
                year="2005",
                track="1/15",
            )
            journal = root / "plan.json"
            result = repair_library(root, journal_path=journal)
            self.assertTrue(source.exists())
            self.assertFalse((root / "Triple Seven").exists())
            self.assertEqual(result["mode"], "dry-run")
            self.assertEqual(result["summary"]["planned"], 1)
            self.assertTrue(journal.exists())

    def test_unknown_required_metadata_is_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "song.mp3"
            write_test_mp3(
                source,
                title="Tema",
                artist="Unknown",
                album="Unknown",
                year="2020",
                track="1",
            )
            plan = build_repair_plan(root)
            self.assertEqual(plan["entries"][0]["status"], "skipped")
            self.assertIn("album_artist", plan["entries"][0]["reason"])

    def test_duplicate_destinations_are_all_collisions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            values = {
                "title": "Tema",
                "artist": "Artista",
                "album_artist": "Artista",
                "album": "Album",
                "year": "2024",
                "track": "1",
            }
            write_test_mp3(root / "uno" / "a.mp3", **values)
            write_test_mp3(root / "dos" / "b.mp3", **values)
            plan = build_repair_plan(root)
            self.assertEqual([entry["status"] for entry in plan["entries"]], ["collision", "collision"])

    def test_verified_enrichment_can_add_missing_genre(self):
        metadata = {
            "title": "Tema",
            "artist": "Artista",
            "album_artist": "Artista",
            "album": "Album",
            "year": "2024",
            "track": "1",
        }

        def fake_enricher(values):
            return {**values, "genre": "Rock", "publisher": "Sello"}

        result = prepare_metadata(metadata, enrich=True, enricher=fake_enricher)
        self.assertEqual(result["genre"], "Rock")
        self.assertEqual(result["publisher"], "Sello")
        self.assertEqual(result["publisher"], "Sello")

    def test_apply_creates_backup_and_rollback_restores_original_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "entrada" / "song.mp3"
            write_test_mp3(
                source,
                title="Intro",
                artist="Triple Seven",
                album_artist="Triple Seven",
                album="Rompiendo Los Limites",
                year="2005",
                track="1/15",
            )
            apply_journal = root / "apply.json"
            applied = repair_library(root, apply=True, journal_path=apply_journal)
            migrated = root / "Triple Seven" / "2005 - Rompiendo Los Limites" / "01 - Intro.mp3"
            self.assertFalse(source.exists())
            self.assertTrue(migrated.exists())
            self.assertEqual(applied["summary"]["completed"], 1)
            backup_relative = applied["entries"][0]["tag_backup"]
            self.assertTrue((apply_journal.parent / backup_relative).exists())

            rollback_journal = root / "rollback.json"
            rolled_back = rollback_library_repair(
                root,
                apply_journal,
                journal_path=rollback_journal,
            )
            self.assertTrue(source.exists())
            self.assertFalse(migrated.exists())
            self.assertEqual(rolled_back["summary"]["completed"], 1)
            self.assertEqual(json.loads(rollback_journal.read_text(encoding="utf-8"))["status"], "completed")

    def test_rollback_recovers_move_left_between_journal_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "entrada" / "song.mp3"
            write_test_mp3(
                source,
                title="Tema",
                artist="Artista",
                album_artist="Artista",
                album="Album",
                year="2024",
                track="1",
            )
            apply_journal = root / "apply.json"
            repair_library(root, apply=True, journal_path=apply_journal)
            interrupted = json.loads(apply_journal.read_text(encoding="utf-8"))
            interrupted["entries"][0]["status"] = "moved"
            apply_journal.write_text(json.dumps(interrupted), encoding="utf-8")

            rolled_back = rollback_library_repair(root, apply_journal, journal_path=root / "rollback.json")
            self.assertTrue(source.exists())
            self.assertEqual(rolled_back["summary"]["completed"], 1)


if __name__ == "__main__":
    unittest.main()
