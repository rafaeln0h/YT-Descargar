import os
import unittest
from unittest.mock import patch

from ymd.acoustid import lookup_acoustid_file, parse_acoustid_payload


class AcoustIDTests(unittest.TestCase):
    def test_parses_only_confident_match(self):
        result = parse_acoustid_payload(
            {
                "results": [
                    {
                        "id": "acoustid-id",
                        "score": 0.97,
                        "recordings": [
                            {
                                "id": "recording-id",
                                "title": "Track",
                                "artists": [{"name": "Artist"}],
                                "releasegroups": [{"id": "group-id", "title": "Album"}],
                            }
                        ],
                    }
                ]
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["confidence"], 0.97)
        self.assertEqual(result["fields"]["musicbrainz_recordingid"], "recording-id")

    def test_low_score_is_not_accepted(self):
        result = parse_acoustid_payload({"results": [{"id": "weak", "score": 0.4}]})
        self.assertEqual(result["status"], "not_found")

    @patch.dict(os.environ, {}, clear=True)
    def test_no_key_skips_before_file_or_tool_checks(self):
        result = lookup_acoustid_file("missing.mp3")
        self.assertEqual(result["status"], "disabled")


if __name__ == "__main__":
    unittest.main()
