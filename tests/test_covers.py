import io
import tempfile
import unittest
from pathlib import Path

from mutagen.id3 import ID3
from PIL import Image

from ymd.covers import (
    clean_album,
    clean_artist,
    musicbrainz_release_matches,
    normalize_cover_bytes,
    write_cover,
)


class CoverTests(unittest.TestCase):
    def test_cleans_channel_and_collection_labels_for_search(self):
        self.assertEqual(clean_artist("Marcos Witt Oficial"), "Marcos Witt")
        self.assertEqual(clean_album("2026 - Album - Dios al Mundo Amó"), "Dios al Mundo Amó")

    def test_musicbrainz_release_requires_exact_artist_and_album(self):
        wanted = {"title": "Dios al Mundo Amó", "artist-credit-phrase": "Marcos Witt"}
        wrong_album = {"title": "Dios de pactos", "artist-credit-phrase": "Marcos Witt"}
        self.assertTrue(musicbrainz_release_matches(wanted, "Marcos Witt", "Dios al Mundo Amo"))
        self.assertFalse(musicbrainz_release_matches(wrong_album, "Marcos Witt", "Dios al Mundo Amo"))

    def test_rectangular_thumbnail_is_center_cropped_to_square(self):
        image = Image.new("RGB", (1200, 675), "#111111")
        for x in range(263, 938):
            for y in range(675):
                image.putpixel((x, y), (220, 30, 50))
        raw = io.BytesIO()
        image.save(raw, format="JPEG", quality=95)

        cover, width, height = normalize_cover_bytes(raw.getvalue())

        self.assertEqual((width, height), (675, 675))
        with Image.open(io.BytesIO(cover)) as result:
            self.assertEqual(result.size, (675, 675))
            red, green, blue = result.getpixel((10, 337))
            self.assertGreater(red, 180)
            self.assertLess(green, 70)
            self.assertLess(blue, 80)

    def test_replaces_mp3_front_cover(self):
        cover_image = Image.new("RGB", (600, 600), "#ff0033")
        raw = io.BytesIO()
        cover_image.save(raw, format="JPEG")
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder) / "song.mp3"
            media.write_bytes(b"")
            write_cover(media, raw.getvalue())
            frames = ID3(media).getall("APIC")
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].desc, "Front Cover")


if __name__ == "__main__":
    unittest.main()
