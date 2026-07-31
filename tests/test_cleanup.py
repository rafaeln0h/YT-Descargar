import json
import tempfile
import unittest
from pathlib import Path

from ymd.cleanup import find_generated_sidecars, remove_generated_sidecars


class CleanupTests(unittest.TestCase):
    def test_removes_only_verified_legacy_sidecars(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            media = root / "song.mp3"
            media.write_bytes(b"audio")
            generated = root / "song.info.json"
            generated.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "media_file": "song.mp3",
                        "metadata": {"title": "Song"},
                    }
                ),
                encoding="utf-8",
            )
            unrelated = root / "keep.info.json"
            unrelated.write_text('{"application": "other"}', encoding="utf-8")

            self.assertEqual(find_generated_sidecars(root), [generated.resolve()])
            self.assertEqual(remove_generated_sidecars(root), [generated.resolve()])
            self.assertFalse(generated.exists())
            self.assertTrue(unrelated.exists())


if __name__ == "__main__":
    unittest.main()
