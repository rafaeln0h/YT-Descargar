import unittest
from unittest.mock import patch

from ymd.enrichment import _pick_release, enrich_metadata, parse_musicbrainz_recording


class EnrichmentTests(unittest.TestCase):
    def test_prefers_earliest_equivalent_official_album_release(self):
        picked = _pick_release(
            {
                "releases": [
                    {"id": "reissue", "title": "Album", "status": "Official", "date": "2021"},
                    {"id": "original", "title": "Album", "status": "Official", "date": "1991"},
                ]
            },
            "Album",
        )
        self.assertEqual(picked["id"], "original")

    def test_parses_high_value_musicbrainz_fields(self):
        result = parse_musicbrainz_recording(
            {
                "id": "recording-id",
                "score": 100,
                "title": "Canción",
                "artist-credit": [{"name": "Artista", "artist": {"id": "artist-id", "name": "Artista"}}],
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
        self.assertNotIn("genre", result, "MusicBrainz tags are not automatically genres")

    def test_parses_release_genres_track_position_and_credits(self):
        result = parse_musicbrainz_recording(
            {
                "id": "recording-id",
                "score": 99,
                "artist-credit": [{"artist": {"id": "a1", "name": "Artist"}}],
                "genres": [{"name": "Latin", "count": 2}],
                "relations": [
                    {
                        "type": "composer",
                        "artist": {"id": "writer-id", "name": "Writer"},
                    }
                ],
                "releases": [
                    {
                        "id": "release-id",
                        "title": "Album",
                        "release-group": {"id": "group-id"},
                    }
                ],
            },
            requested_album="Album",
            release_detail={
                "id": "release-id",
                "title": "Album",
                "date": "2005-03-01",
                "artist-credit": [{"artist": {"id": "a1", "name": "Artist"}}],
                "release-group": {"id": "group-id"},
                "label-info": [{"catalog-number": "CAT-1", "label": {"name": "Label"}}],
                "media": [
                    {
                        "position": 1,
                        "track-count": 2,
                        "tracks": [
                            {"position": 1, "recording": {"id": "other"}},
                            {"position": 2, "recording": {"id": "recording-id"}},
                        ],
                    }
                ],
            },
            release_group_detail={
                "id": "group-id",
                "primary-type": "Album",
                "genres": [{"name": "Gospel", "count": 8}],
            },
        )
        self.assertEqual(result["genre"], "Gospel")
        self.assertEqual(result["genres"], ["Gospel", "Latin"])
        self.assertEqual(result["track"], 2)
        self.assertEqual(result["track_total"], 2)
        self.assertEqual(result["publisher"], "Label")
        self.assertEqual(result["composer"], "Writer")
        self.assertEqual(result["credits"][0]["role"], "composer")

    @patch("ymd.enrichment.musicbrainz_enrichment")
    def test_orchestrator_reports_provenance_and_missing_fields(self, musicbrainz):
        musicbrainz.return_value = {
            "provider": "musicbrainz",
            "status": "ok",
            "fields": {"year": "2005", "genre": "Gospel"},
            "confidence": 0.97,
            "reference": "recording-id",
            "reason": "",
        }
        result = enrich_metadata(
            {"artist": "Artist", "title": "Track", "album": "Album"},
            use_ytmusic=False,
            use_acoustid=False,
            use_discogs=False,
        )
        self.assertEqual(result["metadata"]["year"], "2005")
        self.assertEqual(result["provenance"]["year"]["source"], "musicbrainz")
        self.assertEqual(result["confidence"]["genre"], 0.97)
        self.assertIn("isrc", result["unavailable"])

    @patch("ymd.discogs.lookup_discogs_release")
    def test_discogs_fallback_only_fills_empty_fields(self, discogs):
        discogs.return_value = {
            "provider": "discogs",
            "status": "ok",
            "fields": {
                "genre": "Latin",
                "genres": ["Latin"],
                "styles": ["Gospel"],
                "year": 2005,
                "publisher": "Label",
                "catalog_number": "CAT-7",
            },
            "confidence": 0.94,
            "reference": "release-7",
            "reason": "",
        }
        result = enrich_metadata(
            {
                "artist": "Artist",
                "title": "Track",
                "album": "Album",
                "genre": "Rock",
                "year": 1991,
            },
            use_musicbrainz=False,
            use_ytmusic=False,
            use_acoustid=False,
        )
        self.assertEqual(result["metadata"]["genre"], "Rock")
        self.assertEqual(result["metadata"]["year"], 1991)
        self.assertEqual(result["metadata"]["publisher"], "Label")
        self.assertEqual(result["metadata"]["styles"], ["Gospel"])
        self.assertNotIn("genre", result["provenance"])
        self.assertEqual(result["provenance"]["publisher"]["source"], "discogs")


if __name__ == "__main__":
    unittest.main()
