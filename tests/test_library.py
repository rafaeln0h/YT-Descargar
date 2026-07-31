import tempfile
import unittest
from pathlib import Path

from ymd.library import (
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


if __name__ == "__main__":
    unittest.main()

