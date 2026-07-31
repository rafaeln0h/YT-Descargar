import tempfile
import unittest
from pathlib import Path

from ymd.updates import check_latest_release, is_newer_version, version_parts


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


class UpdateTests(unittest.TestCase):
    def test_numeric_release_comparison(self):
        self.assertEqual(version_parts("v0.013"), (0, 13))
        self.assertTrue(is_newer_version("v0.13", "0.012"))
        self.assertFalse(is_newer_version("v0.012", "0.012"))

    def test_latest_release_is_cached_and_sanitized(self):
        calls = []

        def fake_get(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse(
                200,
                {
                    "tag_name": "v0.013",
                    "name": "Metadata playlists",
                    "html_url": "https://github.com/rafaeln0h/YT-Descargar/releases/tag/v0.013",
                    "body": "Cambios",
                    "published_at": "2026-08-01T00:00:00Z",
                },
                {"ETag": '"release-etag"'},
            )

        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "updates.json"
            first = check_latest_release("0.012", cache_file=cache, http_get=fake_get)
            second = check_latest_release("0.012", cache_file=cache, http_get=fake_get)

        self.assertTrue(first["update_available"])
        self.assertEqual(first["latest_release"]["tag"], "v0.013")
        self.assertEqual(second["source"], "cache")
        self.assertEqual(len(calls), 1)

    def test_no_release_does_not_report_an_update(self):
        calls = []

        def no_release(*_args, **_kwargs):
            calls.append(True)
            return FakeResponse(404)

        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "updates.json"
            result = check_latest_release(
                "0.012",
                cache_file=cache,
                http_get=no_release,
            )
            cached = check_latest_release("0.012", cache_file=cache, http_get=no_release)
        self.assertEqual(result["status"], "no_release")
        self.assertFalse(result["update_available"])
        self.assertEqual(cached["source"], "cache")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
