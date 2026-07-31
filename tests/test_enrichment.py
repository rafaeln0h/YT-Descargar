import unittest

from ymd.enrichment import parse_musicbrainz_recording


class EnrichmentTests(unittest.TestCase):
    def test_parses_high_value_musicbrainz_fields(self):
        result = parse_musicbrainz_recording(
            {
                "id": "recording-id",
                "score": 100,
                "title": "Canción",
                "artist-credit": [
                    {"name": "Artista", "artist": {"id": "artist-id", "name": "Artista"}}
                ],
                "isrcs": ["MXABC2600001"],
                "tags": [{"name": "pop", "count": 10}],
                "releases": [
                    {
                        "id": "release-id",
                        "title": "Álbum",
                        "date": "2026-07-31",
                        "country": "MX",
                        "status": "Official",
                        "barcode": "7500000000000",
                        "release-group": {
                            "id": "release-group-id",
                            "primary-type": "Album",
                        },
                        "label-info": [
                            {
                                "catalog-number": "CAT-012",
                                "label": {"name": "Sello"},
                            }
                        ],
                        "text-representation": {"language": "spa"},
                        "media": [{"track-count": 12}],
                    }
                ],
            },
            requested_album="Álbum",
        )
        self.assertEqual(result["musicbrainz_recordingid"], "recording-id")
        self.assertEqual(result["musicbrainz_artistids"], "artist-id")
        self.assertEqual(result["year"], "2026")
        self.assertEqual(result["publisher"], "Sello")
        self.assertEqual(result["catalog_number"], "CAT-012")
        self.assertEqual(result["isrc"], "MXABC2600001")


if __name__ == "__main__":
    unittest.main()
