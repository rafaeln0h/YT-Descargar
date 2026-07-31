import os
import unittest
from unittest.mock import patch

from ymd.discogs import lookup_discogs_release, parse_discogs_result


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class DiscogsTests(unittest.TestCase):
    def test_parses_requested_release_fields(self):
        fields = parse_discogs_result(
            {
                "genre": ["Latin"],
                "style": ["Gospel"],
                "year": "2005",
                "label": ["Label"],
                "catno": "CAT-7",
            }
        )
        self.assertEqual(fields["genre"], "Latin")
        self.assertEqual(fields["styles"], ["Gospel"])
        self.assertEqual(fields["publisher"], "Label")

    def test_accepts_only_exact_artist_and_album(self):
        def fake_get(*_args, **_kwargs):
            return FakeResponse(
                {
                    "results": [
                        {"title": "Other Artist - Album", "year": 2004},
                        {
                            "title": "Triple Seven - Rompiendo Los Limites",
                            "year": 2005,
                            "genre": ["Latin"],
                            "style": ["Gospel"],
                            "label": ["People Music"],
                            "catno": "PM-1",
                            "resource_url": "https://api.discogs.com/releases/7",
                        },
                    ]
                }
            )

        result = lookup_discogs_release(
            {"artist": "Triple Seven", "album": "Rompiendo Los Limites"},
            token="token",
            http_get=fake_get,
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["fields"]["year"], 2005)
        self.assertEqual(result["reference"], "https://api.discogs.com/releases/7")

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_token_is_disabled_without_http(self):
        result = lookup_discogs_release({"artist": "Artist", "album": "Album"})
        self.assertEqual(result["status"], "disabled")


if __name__ == "__main__":
    unittest.main()
