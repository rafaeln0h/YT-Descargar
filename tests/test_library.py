import tempfile
import unittest
from pathlib import Path

from ymd.library import (
    build_library_catalog,
    decode_media_id,
    encode_media_id,
    resolve_media_path,
    scan_library,
)


class LibraryTests(unittest.TestCase):
    def test_media_id_roundtrip(self):
        relative = Path("Artista") / "Album" / "01 - Cancion.mp3"
        self.assertEqual(decode_media_id(encode_media_id(relative)), relative)

    def test_rejects_traversal(self):
        token = encode_media_id(Path("..") / "secreto.mp3")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                resolve_media_path(directory, token)

    def test_scan_filters_non_media(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "track.mp3").write_bytes(b"not-a-real-mp3")
            (root / "cover.jpg").write_bytes(b"image")
            items = scan_library(root)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["name"], "track.mp3")
            self.assertEqual(items[0]["kind"], "audio")

    def test_scan_prunes_deleted_files_without_failing(self):
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "temporary.mp3"
            media.write_bytes(b"not-a-real-mp3")
            self.assertEqual(len(scan_library(directory)), 1)
            media.unlink()
            self.assertEqual(scan_library(directory), [])

    def test_catalog_keeps_same_album_title_separate_by_artist(self):
        items = [
            {
                "id": "a1",
                "title": "Uno",
                "artist": "Artista A",
                "album_artist": "Artista A",
                "album": "Grandes éxitos",
                "track": "2/2",
                "duration": 120,
                "kind": "audio",
                "has_cover": True,
                "has_lyrics": True,
                "artwork_url": "/cover/a1",
            },
            {
                "id": "b1",
                "title": "Dos",
                "artist": "Artista B",
                "album_artist": "Artista B",
                "album": "Grandes éxitos",
                "track": "1/1",
                "duration": 180,
                "kind": "audio",
                "has_cover": False,
                "has_lyrics": False,
                "artwork_url": "",
            },
        ]
        catalog = build_library_catalog(items)
        self.assertEqual(catalog["summary"]["artists"], 2)
        self.assertEqual(catalog["summary"]["albums"], 2)
        self.assertEqual(catalog["summary"]["with_lyrics"], 1)


if __name__ == "__main__":
    unittest.main()
