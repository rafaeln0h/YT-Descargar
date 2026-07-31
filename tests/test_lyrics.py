import unittest

from ymd.lyrics import parse_lrclib_payload, pick_lrclib_candidate


class LyricsTests(unittest.TestCase):
    def test_prefers_plain_lyrics(self):
        result = parse_lrclib_payload(
            {
                "id": 42,
                "plainLyrics": "Primera línea\nSegunda línea",
                "syncedLyrics": "[00:01.00]Otra línea",
                "instrumental": False,
            }
        )
        self.assertEqual(result["lyrics"], "Primera línea\nSegunda línea")
        self.assertEqual(result["lrclib_id"], 42)

    def test_converts_synced_lyrics_when_plain_is_missing(self):
        result = parse_lrclib_payload(
            {
                "id": 43,
                "plainLyrics": "",
                "syncedLyrics": "[00:01.00]Primera línea\n[00:04.25]Segunda línea",
                "instrumental": False,
            }
        )
        self.assertEqual(result["lyrics"], "Primera línea\nSegunda línea")

    def test_does_not_invent_lyrics_for_instrumental_tracks(self):
        result = parse_lrclib_payload({"id": 44, "instrumental": True})
        self.assertTrue(result["instrumental"])
        self.assertNotIn("lyrics", result)

    def test_conservative_search_accepts_official_channel_suffix(self):
        result = pick_lrclib_candidate(
            [
                {
                    "id": 45,
                    "trackName": "Dios al mundo amo",
                    "artistName": "Marcos Witt",
                    "duration": 274,
                    "plainLyrics": "Texto",
                },
                {
                    "id": 46,
                    "trackName": "Otra canción",
                    "artistName": "Marcos Witt",
                    "duration": 274,
                    "plainLyrics": "Incorrecta",
                },
            ],
            artist="Marcos Witt Oficial",
            title="Dios al mundo amó",
            duration=273,
        )
        self.assertEqual(result["lrclib_id"], 45)
        self.assertEqual(result["lyrics"], "Texto")


if __name__ == "__main__":
    unittest.main()
