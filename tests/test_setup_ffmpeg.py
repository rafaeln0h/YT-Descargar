import tempfile
import unittest
import zipfile
from pathlib import Path

from setup_ffmpeg import _safe_extract


class SetupFfmpegTests(unittest.TestCase):
    def test_safe_extract_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "malicious.zip"
            with zipfile.ZipFile(archive, "w") as zip_file:
                zip_file.writestr("../escape.txt", "blocked")

            with zipfile.ZipFile(archive) as zip_file:
                with self.assertRaises(ValueError):
                    _safe_extract(zip_file, root / "extract")

            self.assertFalse((root.parent / "escape.txt").exists())


if __name__ == "__main__":
    unittest.main()
