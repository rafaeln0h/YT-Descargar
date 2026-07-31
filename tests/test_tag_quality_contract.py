import tempfile
from pathlib import Path

from mutagen.id3 import ID3

from ymd.enrichment import parse_musicbrainz_recording
from ymd.metadata import annotate_metadata_availability, write_metadata


def _write_id3(metadata: dict) -> ID3:
    """Write tags to a disposable MP3 shell and return the parsed ID3 data."""

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "track.mp3"
        path.write_bytes(b"")
        write_metadata(path, metadata)
        return ID3(path)


def _txxx(tags: ID3) -> dict[str, str]:
    return {
        frame.desc: "; ".join(str(value) for value in frame.text)
        for frame in tags.getall("TXXX")
    }


def test_empty_disc_does_not_create_a_zero_tpos_frame():
    tags = _write_id3(
        {
            "title": "Cancion",
            "artist": "Artista",
            "album": "Album",
            "track": 1,
            "disc": "",
            "disc_total": "",
        }
    )

    assert tags.getall("TPOS") == []


def test_full_release_and_original_dates_use_standard_id3_frames():
    tags = _write_id3(
        {
            "title": "Cancion",
            "artist": "Artista",
            "album": "Album",
            "release_date": "2026-07-31",
            "original_release_date": "2005-03-15",
        }
    )

    assert str(tags["TDRC"].text[0]) == "2026-07-31"
    assert str(tags["TDOR"].text[0]) == "2005-03-15"


def test_picard_and_acoustid_identifiers_use_compatible_id3_names():
    tags = _write_id3(
        {
            "title": "Cancion",
            "artist": "Artista",
            "album": "Album",
            "musicbrainz_recordingid": "recording-id",
            "musicbrainz_releaseid": "release-id",
            "musicbrainz_releasegroupid": "release-group-id",
            "musicbrainz_artistids": "artist-id-1;artist-id-2",
            "acoustid_id": "acoustid-track-id",
            "acoustid_fingerprint": "AQADtM...",
        }
    )
    custom = _txxx(tags)

    ufids = tags.getall("UFID:http://musicbrainz.org")
    assert len(ufids) == 1
    assert ufids[0].data == b"recording-id"
    assert custom["MusicBrainz Album Id"] == "release-id"
    assert custom["MusicBrainz Release Group Id"] == "release-group-id"
    assert custom["MusicBrainz Artist Id"] == "artist-id-1;artist-id-2"
    assert custom["Acoustid Id"] == "acoustid-track-id"
    assert custom["Acoustid Fingerprint"] == "AQADtM..."


def test_credits_and_explicit_rating_are_preserved_in_id3():
    tags = _write_id3(
        {
            "title": "Cancion",
            "artist": "Interprete",
            "album": "Album",
            "composer": "Compositor",
            "lyricist": "Letrista",
            "producer": "Productor",
            "conductor": "Director",
            "remixer": "Remixer",
            "performers": ["Voz: Interprete", "Guitarra: Musico"],
            "explicit": True,
        }
    )
    custom = _txxx(tags)

    assert str(tags["TCOM"].text[0]) == "Compositor"
    assert str(tags["TEXT"].text[0]) == "Letrista"
    assert str(tags["TPE3"].text[0]) == "Director"
    assert str(tags["TPE4"].text[0]) == "Remixer"
    assert custom["PRODUCER"] == "Productor"
    assert custom["PERFORMERS"] == "Voz: Interprete; Guitarra: Musico"
    assert custom["ITUNESADVISORY"] == "1"


def test_missing_field_report_is_audit_only_and_never_invents_genre():
    result = annotate_metadata_availability(
        {
            "title": "Cancion",
            "artist": "Artista",
            "album": "Album",
            "genre": "",
            "composer": "",
            "producer": "",
            "publisher": "",
            "isrc": "",
            "language": "",
            "youtube_id": "video-id",
        }
    )

    assert result["genre"] == ""
    assert set(result["metadata_missing"].split("; ")) == {
        "genre",
        "composer",
        "producer",
        "publisher",
        "isrc",
        "language",
    }
    assert result["metadata_sources_used"] == "yt-dlp"
    assert result["enrichment_status"] == "partial"


def test_missing_field_report_marks_complete_metadata_without_fabrication():
    result = annotate_metadata_availability(
        {
            "genre": "Hip hop",
            "composer": "Compositor",
            "producer": "Productor",
            "publisher": "Sello",
            "isrc": "MXABC2600001",
            "language": "spa",
            "metadata_confidence": 0.96,
            "musicbrainz_recordingid": "recording-id",
            "acoustid_id": "acoustid-id",
        }
    )

    assert result["metadata_missing"] == ""
    assert result["enrichment_status"] == "complete"
    assert result["metadata_confidence"] == 0.96
    assert result["metadata_sources_used"] == "musicbrainz; acoustid"


def test_musicbrainz_exposes_original_release_date_separately():
    result = parse_musicbrainz_recording(
        {
            "id": "recording-id",
            "score": 100,
            "title": "Cancion",
            "artist-credit": [
                {"name": "Artista", "artist": {"id": "artist-id", "name": "Artista"}}
            ],
            "releases": [
                {
                    "id": "release-id",
                    "title": "Album remasterizado",
                    "date": "2026-07-31",
                    "status": "Official",
                    "release-group": {
                        "id": "release-group-id",
                        "primary-type": "Album",
                        "first-release-date": "2005-03-15",
                    },
                }
            ],
        },
        requested_album="Album remasterizado",
    )

    assert result["release_date"] == "2026-07-31"
    assert result["original_release_date"] == "2005-03-15"
