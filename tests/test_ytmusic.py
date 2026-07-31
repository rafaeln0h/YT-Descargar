import unittest

from ymd.ytmusic import lookup_ytmusic_album, parse_ytmusic_album


class FakeYTMusic:
    def get_album_browse_id(self, playlist_id):
        self.playlist_id = playlist_id
        return "MPREb_album"

    def get_album(self, browse_id):
        self.browse_id = browse_id
        return {
            "title": "Rompiendo Los Limites",
            "year": "2005",
            "type": "Album",
            "isExplicit": False,
            "artists": [{"name": "Triple Seven"}],
            "tracks": [
                {
                    "videoId": "video-1",
                    "title": "Intro",
                    "artists": [{"name": "Triple Seven"}],
                    "isExplicit": True,
                    "creditsBrowseId": "MPTCvideo-1",
                }
            ],
        }

    def get_song_credits(self, browse_id):
        self.credits_browse_id = browse_id
        return {
            "performed_by": {"data": ["Triple Seven"]},
            "written_by": {"data": ["Autor Uno"]},
            "produced_by": {"data": ["Productor Uno"]},
            "music_metadata_provided_by": {"data": ["Proveedor"]},
        }


class YTMusicTests(unittest.TestCase):
    def test_parses_album_and_exact_track_without_guessing_credits(self):
        fields = parse_ytmusic_album(
            FakeYTMusic().get_album("MPREb_album"),
            {"youtube_id": "video-1", "title": "Intro", "artist": "Triple Seven"},
        )
        self.assertEqual(fields["album"], "Rompiendo Los Limites")
        self.assertEqual(fields["year"], "2005")
        self.assertTrue(fields["explicit"])
        self.assertEqual(fields["track"], 1)
        self.assertNotIn("credits", fields)

    def test_resolves_official_playlist_to_browse_id(self):
        client = FakeYTMusic()
        result = lookup_ytmusic_album(
            {
                "playlist_url": "https://music.youtube.com/playlist?list=OLAK5uy_example",
                "youtube_id": "video-1",
                "title": "Intro",
                "artist": "Triple Seven",
            },
            client=client,
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["reference"], "MPREb_album")
        self.assertEqual(client.playlist_id, "OLAK5uy_example")
        self.assertEqual(result["fields"]["composer"], "Autor Uno")
        self.assertEqual(result["fields"]["producer"], "Productor Uno")
        self.assertEqual(client.credits_browse_id, "MPTCvideo-1")

    def test_without_album_identity_is_not_applicable(self):
        result = lookup_ytmusic_album({"title": "Track"}, client=FakeYTMusic())
        self.assertEqual(result["status"], "not_applicable")


if __name__ == "__main__":
    unittest.main()
