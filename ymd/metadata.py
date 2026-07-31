"""Cross-format media tag writing.

The downloader used to contain separate, minimal MP3 and M4A branches.  This
module provides one normalized metadata model and supports common music-library
fields across MP3, M4A/MP4, FLAC, OGG/OPUS and WAV where the container permits
them.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Mapping

from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.id3 import (
    COMM,
    ID3,
    TALB,
    TBPM,
    TCOM,
    TCOP,
    TDOR,
    TDRC,
    TENC,
    TEXT,
    TIT1,
    TIT2,
    TKEY,
    TLAN,
    TPE1,
    TPE2,
    TPE3,
    TPE4,
    TPOS,
    TPUB,
    TRCK,
    TSOA,
    TSOC,
    TSOP,
    TSOT,
    TSRC,
    TXXX,
    UFID,
    USLT,
    ID3NoHeaderError,
)
from mutagen.mp4 import MP4
from mutagen.wave import WAVE

LOGGER = logging.getLogger(__name__)

ADVANCED_FIELDS = (
    "album_artist",
    "genre",
    "composer",
    "publisher",
    "copyright",
    "language",
    "comment",
    "bpm",
    "disc",
    "disc_total",
    "track_total",
    "isrc",
    "grouping",
    "compilation",
    "explicit",
    "release_type",
    "release_country",
    "release_status",
    "catalog_number",
    "barcode",
    "mood",
    "release_date",
    "original_release_date",
    "lyricist",
    "producer",
    "conductor",
    "remixer",
    "performers",
    "key",
    "title_sort",
    "artist_sort",
    "album_sort",
    "album_artist_sort",
    "composer_sort",
    "replaygain_track_gain",
    "replaygain_track_peak",
    "loudness_integrated",
    "true_peak",
)

PROVENANCE_FIELDS = (
    "youtube_id",
    "channel",
    "channel_id",
    "uploader",
    "uploader_id",
    "upload_date",
    "release_date",
    "duration",
    "description",
    "license",
    "categories",
    "keywords",
    "chapters_json",
    "webpage_url",
    "thumbnail_url",
    "extractor",
    "format_id",
    "audio_codec",
    "video_codec",
    "resolution",
    "source_bitrate",
    "musicbrainz_recordingid",
    "musicbrainz_releaseid",
    "musicbrainz_releasegroupid",
    "musicbrainz_artistids",
    "musicbrainz_score",
    "acoustid_id",
    "acoustid_fingerprint",
    "metadata_sources_used",
    "metadata_confidence",
    "metadata_missing",
    "enrichment_status",
    "enrichment_providers_json",
    "credits_source",
    "credits_json",
    "written_by",
    "metadata_provider",
    "explicit_known",
    "audio_analysis_source",
    "audio_analysis_status",
    "audio_analysis_error",
    "collection_kind",
    "playlist_title",
    "playlist_owner",
    "playlist_url",
    "playlist_position",
    "playlist_total",
    "playlist_cover_url",
    "cover_source",
    "cover_source_url",
    "cover_width",
    "cover_height",
)

HIGH_VALUE_OPTIONAL_FIELDS = (
    "genre",
    "composer",
    "producer",
    "publisher",
    "isrc",
    "language",
)


def _clean(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return value


def normalize_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Return a stable tag dictionary with safe numeric values."""

    result = {key: _clean(value) for key, value in dict(metadata).items()}
    result.setdefault("title", "Unknown")
    result.setdefault("artist", "Unknown")
    result.setdefault("album", "Unknown")
    result.setdefault("year", "")
    result.setdefault("track", 1)
    result.setdefault("genre", "")

    for key in ("release_date", "original_release_date"):
        if result.get(key):
            result[key] = _normalized_date(result[key])

    for key in ("track", "track_total", "disc", "disc_total", "bpm"):
        value = result.get(key)
        if value in ("", None):
            continue
        try:
            result[key] = max(0, int(float(value)))
        except (TypeError, ValueError):
            result[key] = ""

    for key in ("compilation", "explicit"):
        value = result.get(key)
        if isinstance(value, str):
            result[key] = value.lower() in {"1", "true", "yes", "si", "sí"}
        else:
            result[key] = bool(value)
    return result


def apply_metadata_defaults(
    metadata: Mapping[str, Any],
    defaults: Mapping[str, Any] | None = None,
    *,
    source_url: str = "",
) -> dict[str, Any]:
    """Fill blank advanced fields without overwriting detected/manual values."""

    merged = dict(metadata)
    for key, value in dict(defaults or {}).items():
        if key in ADVANCED_FIELDS and merged.get(key) in (None, ""):
            merged[key] = value
    if source_url:
        merged["source_url"] = source_url
    merged.setdefault("encoded_by", "YT-Descargar")
    return normalize_metadata(merged)


def _joined(value: Any, *, limit: int = 1000) -> str:
    if isinstance(value, (list, tuple, set)):
        text = "; ".join(str(item) for item in value if item not in ("", None))
    else:
        text = str(value or "")
    return text[:limit]


def _normalized_date(value: Any) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if re.fullmatch(r"\d{6}", text):
        return f"{text[:4]}-{text[4:6]}"
    return text


def annotate_metadata_availability(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Record enrichment completeness without fabricating unavailable values."""

    result = dict(metadata)
    if result.get("credits") and not result.get("credits_json"):
        result["credits_json"] = json.dumps(
            result["credits"], ensure_ascii=False, separators=(",", ":")
        )[:8000]
    missing = [
        field
        for field in HIGH_VALUE_OPTIONAL_FIELDS
        if result.get(field) in ("", None, [], {})
    ]
    existing = result.get("metadata_missing")
    if isinstance(existing, str):
        missing.extend(part.strip() for part in existing.split(";") if part.strip())
    elif isinstance(existing, (list, tuple, set)):
        missing.extend(str(part).strip() for part in existing if str(part).strip())
    result["metadata_missing"] = "; ".join(dict.fromkeys(missing))

    sources = result.get("metadata_sources_used")
    if not sources:
        detected_sources = ["yt-dlp"] if result.get("youtube_id") else []
        if result.get("musicbrainz_recordingid") or result.get("musicbrainz_releaseid"):
            detected_sources.append("musicbrainz")
        if result.get("acoustid_id"):
            detected_sources.append("acoustid")
        result["metadata_sources_used"] = "; ".join(detected_sources)
    result.setdefault(
        "enrichment_status",
        "partial" if missing else "complete",
    )
    return result


def merge_ytdlp_metadata(
    metadata: Mapping[str, Any],
    info: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Merge public extractor metadata without copying signed stream URLs."""

    merged = dict(metadata)
    source = dict(info or {})
    requested = source.get("requested_downloads") or []
    stream = requested[0] if requested and isinstance(requested[0], dict) else {}
    artists = source.get("artists") or source.get("creators") or []
    composers = source.get("composers") or []
    chapters = source.get("chapters") or []
    upload_date = str(source.get("upload_date") or "")
    release_date = str(source.get("release_date") or "")
    release_year = source.get("release_year") or (release_date[:4] if release_date else "")
    collection_kind = str(merged.get("collection_kind") or "")
    if not release_year and collection_kind not in {"official_album"}:
        # For ordinary uploads the upload year is still useful, but it must
        # remain distinguishable from RELEASE_DATE in provenance.
        release_year = upload_date[:4] if upload_date else ""

    detected = {
        "title": source.get("track") or source.get("title"),
        "artist": _joined(artists)
        or source.get("artist")
        or source.get("creator")
        or source.get("uploader"),
        "album": source.get("album"),
        "album_artist": source.get("album_artist"),
        "composer": _joined(composers) or source.get("composer"),
        "genre": _joined(source.get("genres") or source.get("genre")),
        "year": release_year,
        "track": source.get("track_number"),
        "track_total": source.get("track_count"),
        "disc": source.get("disc_number"),
        "disc_total": source.get("disc_count"),
        "release_date": release_date,
        "explicit": source.get("age_limit") not in (None, 0, "0") if source.get("age_limit") is not None else None,
        "youtube_id": source.get("id"),
        "channel": source.get("channel"),
        "channel_id": source.get("channel_id"),
        "uploader": source.get("uploader"),
        "uploader_id": source.get("uploader_id"),
        "upload_date": upload_date,
        "duration": source.get("duration"),
        "description": _joined(source.get("description"), limit=4000),
        "license": source.get("license"),
        "categories": _joined(source.get("categories") or []),
        "keywords": _joined(source.get("tags") or []),
        "chapters_json": (
            json.dumps(chapters, ensure_ascii=False, separators=(",", ":"))[:8000]
            if chapters
            else ""
        ),
        "webpage_url": source.get("webpage_url") or source.get("original_url"),
        "thumbnail_url": source.get("thumbnail"),
        "extractor": source.get("extractor_key") or source.get("extractor"),
        "format_id": stream.get("format_id") or source.get("format_id"),
        "audio_codec": stream.get("acodec") or source.get("acodec"),
        "video_codec": stream.get("vcodec") or source.get("vcodec"),
        "resolution": stream.get("resolution") or source.get("resolution"),
        "source_bitrate": stream.get("abr") or source.get("abr") or source.get("tbr"),
    }
    overwrite_when_authoritative = {"year", "track", "track_total", "disc", "disc_total"}
    for key, value in detected.items():
        if value in ("", None, [], {}):
            continue
        if key in overwrite_when_authoritative or merged.get(key) in ("", None, "Unknown"):
            merged[key] = value

    if collection_kind in {"playlist", "official_album"}:
        # Flat playlist extraction often exposes only the uploader. The full
        # per-track lookup has the authoritative music fields, so prefer those
        # without treating the playlist owner as the recording artist.
        music_artist = _joined(source.get("artists") or source.get("creators") or [])
        music_artist = music_artist or source.get("artist") or source.get("creator")
        if music_artist:
            merged["artist"] = music_artist
        for field, source_field in (
            ("album", "album"),
            ("album_artist", "album_artist"),
            ("composer", "composer"),
        ):
            if source.get(source_field):
                merged[field] = source[source_field]

        if collection_kind == "playlist":
            # Folder/file order and player order must match the playlist even
            # when the original album has a different track number.
            merged["track"] = merged.get("playlist_position") or merged.get("playlist_track") or 1
            merged["track_total"] = merged.get("playlist_total") or merged.get("track_total")
            if merged.get("album") in ("", None, "Unknown"):
                merged["album"] = merged.get("playlist_title") or "Playlist"
            if merged.get("album_artist") in ("", None, "Unknown"):
                merged["album_artist"] = (
                    "Various Artists" if merged.get("compilation") else merged.get("artist")
                )
    if detected.get("webpage_url"):
        merged["source_url"] = detected["webpage_url"]
    return normalize_metadata(annotate_metadata_availability(merged))


def apply_official_album_context(
    items: list[Mapping[str, Any]],
    playlist_title: str,
    track_info: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Fill flat YouTube Music album entries from one full track lookup."""

    clean_title = re.sub(
        r"^\s*album\s*[-:|]\s*",
        "",
        str(playlist_title or ""),
        flags=re.I,
    ).strip()
    artists = track_info.get("artists") or track_info.get("creators") or []
    artist = (
        _joined(artists)
        or _clean(track_info.get("artist"))
        or _clean(track_info.get("album_artist"))
    )
    album = _clean(track_info.get("album")) or clean_title
    album_artist = _clean(track_info.get("album_artist")) or artist
    release_date = str(track_info.get("release_date") or "")
    year = _clean(track_info.get("release_year")) or (release_date[:4] if release_date else "")

    enriched: list[dict[str, Any]] = []
    for index, source in enumerate(items, 1):
        item = dict(source)
        if album:
            item["album"] = item.get("album") or album
        if album_artist:
            item["album_artist"] = item.get("album_artist") or album_artist
        if year:
            item["year"] = item.get("year") or year
        if artist:
            current_artist = str(item.get("artist") or "").strip()
            if not current_artist or re.search(
                r"\s+(oficial|official)\s*$",
                current_artist,
                flags=re.I,
            ):
                item["artist"] = artist
        item["track"] = item.get("track") or item.get("position") or index
        item["track_total"] = item.get("track_total") or len(items)
        enriched.append(item)
    return enriched


def _fraction(current: Any, total: Any) -> str:
    if current in ("", None, 0, "0"):
        return ""
    current_value = str(current)
    return f"{current_value}/{total}" if total not in ("", None, 0, "0") else current_value


def _set_text(tags: ID3, frame_type: type, value: Any, **kwargs: Any) -> None:
    if value not in ("", None):
        tags.add(frame_type(encoding=3, text=[str(value)], **kwargs))


def _write_id3(file_path: str | Path, data: Mapping[str, Any], *, wave: bool = False) -> None:
    if wave:
        audio = WAVE(file_path)
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
    else:
        try:
            tags = ID3(file_path)
        except ID3NoHeaderError:
            tags = ID3()

    for frame_id in (
        "TIT1",
        "TIT2",
        "TALB",
        "TPE1",
        "TPE2",
        "TDRC",
        "TDOR",
        "TRCK",
        "TPOS",
        "TCON",
        "TCOM",
        "TPUB",
        "TCOP",
        "TLAN",
        "TBPM",
        "TSRC",
        "TENC",
        "TEXT",
        "TPE3",
        "TPE4",
        "TSOA",
        "TSOC",
        "TSOP",
        "TSOT",
        "TKEY",
        "COMM",
    ):
        tags.delall(frame_id)

    _set_text(tags, TIT2, data.get("title"))
    _set_text(tags, TPE1, data.get("artist"))
    _set_text(tags, TALB, data.get("album"))
    _set_text(tags, TPE2, data.get("album_artist"))
    _set_text(tags, TDRC, _normalized_date(data.get("release_date") or data.get("year")))
    _set_text(tags, TDOR, _normalized_date(data.get("original_release_date")))
    _set_text(tags, TRCK, _fraction(data.get("track"), data.get("track_total")))
    _set_text(tags, TPOS, _fraction(data.get("disc"), data.get("disc_total")))
    _set_text(tags, TCOM, data.get("composer"))
    _set_text(tags, TPUB, data.get("publisher"))
    _set_text(tags, TCOP, data.get("copyright"))
    _set_text(tags, TLAN, data.get("language"))
    _set_text(tags, TBPM, data.get("bpm"))
    _set_text(tags, TSRC, data.get("isrc"))
    _set_text(tags, TIT1, data.get("grouping"))
    _set_text(tags, TENC, data.get("encoded_by"))
    _set_text(tags, TEXT, data.get("lyricist"))
    _set_text(tags, TPE3, data.get("conductor"))
    _set_text(tags, TPE4, data.get("remixer"))
    _set_text(tags, TSOA, data.get("album_sort"))
    _set_text(tags, TSOC, data.get("composer_sort"))
    _set_text(tags, TSOP, data.get("artist_sort") or data.get("album_artist_sort"))
    _set_text(tags, TSOT, data.get("title_sort"))
    _set_text(tags, TKEY, data.get("key"))

    genre = data.get("genre")
    if genre not in ("", None):
        from mutagen.id3 import TCON

        _set_text(tags, TCON, genre)
    if data.get("comment"):
        tags.add(COMM(encoding=3, lang="eng", desc="", text=[str(data["comment"])]))

    custom_fields = {
        "SOURCE_URL": data.get("source_url"),
        "COMPILATION": "1" if data.get("compilation") else "",
        "ITUNESADVISORY": (
            "1" if data.get("explicit") else ("0" if data.get("explicit_known") else "")
        ),
        **{field.upper(): _joined(data.get(field), limit=8000) for field in PROVENANCE_FIELDS},
        "RELEASE_TYPE": data.get("release_type"),
        "RELEASE_COUNTRY": data.get("release_country"),
        "RELEASE_STATUS": data.get("release_status"),
        "CATALOGNUMBER": data.get("catalog_number"),
        "BARCODE": data.get("barcode"),
        "MOOD": data.get("mood"),
        "PRODUCER": data.get("producer"),
        "PERFORMERS": _joined(data.get("performers"), limit=4000),
        "MusicBrainz Album Id": data.get("musicbrainz_releaseid"),
        "MusicBrainz Release Group Id": data.get("musicbrainz_releasegroupid"),
        "MusicBrainz Artist Id": data.get("musicbrainz_artistids"),
        "Acoustid Id": data.get("acoustid_id"),
        "Acoustid Fingerprint": data.get("acoustid_fingerprint"),
        "REPLAYGAIN_TRACK_GAIN": data.get("replaygain_track_gain"),
        "REPLAYGAIN_TRACK_PEAK": data.get("replaygain_track_peak"),
        "LOUDNESS_INTEGRATED": data.get("loudness_integrated"),
        "TRUE_PEAK": data.get("true_peak"),
    }
    for description, value in custom_fields.items():
        tags.delall("TXXX:" + description)
        if value:
            tags.add(TXXX(encoding=3, desc=description, text=[str(value)]))
    tags.delall("UFID:http://musicbrainz.org")
    if data.get("musicbrainz_recordingid"):
        tags.add(
            UFID(
                owner="http://musicbrainz.org",
                data=str(data["musicbrainz_recordingid"]).encode("ascii", errors="ignore"),
            )
        )
    if data.get("description"):
        tags.add(COMM(encoding=3, lang="eng", desc="DESCRIPTION", text=[str(data["description"])]))

    if wave:
        audio.save()
    else:
        tags.save(file_path, v2_version=4)


def _write_mp4(file_path: str | Path, data: Mapping[str, Any]) -> None:
    audio = MP4(file_path)
    mapping = {
        "\xa9nam": data.get("title"),
        "\xa9ART": data.get("artist"),
        "\xa9alb": data.get("album"),
        "aART": data.get("album_artist"),
        "\xa9day": _normalized_date(data.get("release_date") or data.get("year")),
        "\xa9gen": data.get("genre"),
        "\xa9wrt": data.get("composer"),
        "cprt": data.get("copyright"),
        "\xa9cmt": data.get("comment"),
        "\xa9grp": data.get("grouping"),
        "\xa9too": data.get("encoded_by"),
        "sonm": data.get("title_sort"),
        "soar": data.get("artist_sort"),
        "soal": data.get("album_sort"),
        "soaa": data.get("album_artist_sort"),
        "soco": data.get("composer_sort"),
    }
    for atom, value in mapping.items():
        if value not in ("", None):
            audio[atom] = [str(value)]
    audio["trkn"] = [(int(data.get("track") or 0), int(data.get("track_total") or 0))]
    if data.get("disc") or data.get("disc_total"):
        audio["disk"] = [(int(data.get("disc") or 0), int(data.get("disc_total") or 0))]
    if data.get("bpm"):
        audio["tmpo"] = [int(data["bpm"])]
    if data.get("compilation"):
        audio["cpil"] = [True]
    if data.get("explicit"):
        audio["rtng"] = [4]
    elif data.get("explicit_known"):
        audio["rtng"] = [2]

    freeform = {
        "SOURCE_URL": data.get("source_url"),
        "LANGUAGE": data.get("language"),
        "PUBLISHER": data.get("publisher"),
        "ISRC": data.get("isrc"),
        **{field.upper(): _joined(data.get(field), limit=8000) for field in PROVENANCE_FIELDS},
        "RELEASE_TYPE": data.get("release_type"),
        "RELEASE_COUNTRY": data.get("release_country"),
        "RELEASE_STATUS": data.get("release_status"),
        "CATALOGNUMBER": data.get("catalog_number"),
        "BARCODE": data.get("barcode"),
        "MOOD": data.get("mood"),
        "ORIGINALDATE": data.get("original_release_date"),
        "LYRICIST": data.get("lyricist"),
        "PRODUCER": data.get("producer"),
        "CONDUCTOR": data.get("conductor"),
        "REMIXER": data.get("remixer"),
        "PERFORMERS": _joined(data.get("performers"), limit=4000),
        "INITIALKEY": data.get("key"),
        "MusicBrainz Album Id": data.get("musicbrainz_releaseid"),
        "MusicBrainz Release Group Id": data.get("musicbrainz_releasegroupid"),
        "MusicBrainz Artist Id": data.get("musicbrainz_artistids"),
        "MusicBrainz Track Id": data.get("musicbrainz_recordingid"),
        "Acoustid Id": data.get("acoustid_id"),
        "Acoustid Fingerprint": data.get("acoustid_fingerprint"),
        "REPLAYGAIN_TRACK_GAIN": data.get("replaygain_track_gain"),
        "REPLAYGAIN_TRACK_PEAK": data.get("replaygain_track_peak"),
        "LOUDNESS_INTEGRATED": data.get("loudness_integrated"),
        "TRUE_PEAK": data.get("true_peak"),
    }
    for key, value in freeform.items():
        if value not in ("", None):
            audio[f"----:com.apple.iTunes:{key}"] = [str(value).encode("utf-8")]
    audio.save()


def _write_vorbis(file_path: str | Path, data: Mapping[str, Any]) -> None:
    audio = MutagenFile(file_path, easy=True)
    if audio is None:
        raise ValueError(f"Formato no reconocido: {file_path}")
    if audio.tags is None:
        audio.add_tags()

    mapping = {
        "title": data.get("title"),
        "artist": data.get("artist"),
        "album": data.get("album"),
        "albumartist": data.get("album_artist"),
        "date": _normalized_date(data.get("release_date") or data.get("year")),
        "originaldate": _normalized_date(data.get("original_release_date")),
        "tracknumber": data.get("track"),
        "tracktotal": data.get("track_total"),
        "discnumber": data.get("disc"),
        "disctotal": data.get("disc_total"),
        "genre": data.get("genre"),
        "composer": data.get("composer"),
        "organization": data.get("publisher"),
        "copyright": data.get("copyright"),
        "language": data.get("language"),
        "comment": data.get("comment"),
        "bpm": data.get("bpm"),
        "isrc": data.get("isrc"),
        "grouping": data.get("grouping"),
        "website": data.get("source_url"),
        "encodedby": data.get("encoded_by"),
        "compilation": "1" if data.get("compilation") else "",
        "explicit": "1" if data.get("explicit") else "",
        **{field: _joined(data.get(field), limit=8000) for field in PROVENANCE_FIELDS},
        "release_type": data.get("release_type"),
        "releasecountry": data.get("release_country"),
        "releasestatus": data.get("release_status"),
        "catalognumber": data.get("catalog_number"),
        "barcode": data.get("barcode"),
        "mood": data.get("mood"),
        "lyricist": data.get("lyricist"),
        "producer": data.get("producer"),
        "conductor": data.get("conductor"),
        "remixer": data.get("remixer"),
        "performer": _joined(data.get("performers"), limit=4000),
        "initialkey": data.get("key"),
        "titlesort": data.get("title_sort"),
        "artistsort": data.get("artist_sort"),
        "albumsort": data.get("album_sort"),
        "albumartistsort": data.get("album_artist_sort"),
        "composersort": data.get("composer_sort"),
        "musicbrainz_trackid": data.get("musicbrainz_recordingid"),
        "musicbrainz_albumid": data.get("musicbrainz_releaseid"),
        "musicbrainz_releasegroupid": data.get("musicbrainz_releasegroupid"),
        "musicbrainz_artistid": data.get("musicbrainz_artistids"),
        "acoustid_id": data.get("acoustid_id"),
        "acoustid_fingerprint": data.get("acoustid_fingerprint"),
        "replaygain_track_gain": data.get("replaygain_track_gain"),
        "replaygain_track_peak": data.get("replaygain_track_peak"),
        "loudness_integrated": data.get("loudness_integrated"),
        "true_peak": data.get("true_peak"),
    }
    for key, value in mapping.items():
        if value not in ("", None):
            try:
                audio[key] = [str(value)]
            except Exception:
                # Some Easy* mappings are intentionally conservative. FLAC and
                # Ogg containers still accept the raw Vorbis key.
                if isinstance(audio, FLAC):
                    audio.tags[key.upper()] = [str(value)]
    audio.save()


def write_metadata(file_path: str | Path, metadata: Mapping[str, Any]) -> None:
    """Write normalized tags to a downloaded media file.

    Raises on unsupported/corrupt files; the caller decides whether tagging is
    best-effort or fatal to the overall download.
    """

    path = Path(file_path)
    data = normalize_metadata(annotate_metadata_availability(metadata))
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        _write_id3(path, data)
    elif suffix in {".m4a", ".mp4"}:
        _write_mp4(path, data)
    elif suffix in {".flac", ".ogg", ".oga", ".opus"}:
        _write_vorbis(path, data)
    elif suffix == ".wav":
        _write_id3(path, data, wave=True)
    else:
        LOGGER.info("Tagging skipped for unsupported container: %s", suffix)


def write_lyrics(
    file_path: str | Path,
    lyrics_text: str,
    *,
    language: str = "und",
    source: str = "",
    source_id: str = "",
) -> bool:
    """Embed unsynchronised lyrics in every supported audio container."""

    if not lyrics_text.strip():
        return False

    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        tags.delall("USLT")
        tags.add(USLT(encoding=3, lang=language[:3] or "und", desc="Lyrics", text=lyrics_text))
        for description, value in {
            "LYRICS_SOURCE": source,
            "LYRICS_SOURCE_ID": source_id,
        }.items():
            tags.delall("TXXX:" + description)
            if value:
                tags.add(TXXX(encoding=3, desc=description, text=[str(value)]))
        tags.save(path, v2_version=4)
        return True

    if suffix in {".m4a", ".mp4"}:
        audio = MP4(path)
        audio["\xa9lyr"] = [lyrics_text]
        if source:
            audio["----:com.apple.iTunes:LYRICS_SOURCE"] = [source.encode("utf-8")]
        if source_id:
            audio["----:com.apple.iTunes:LYRICS_SOURCE_ID"] = [source_id.encode("utf-8")]
        audio.save()
        return True

    if suffix in {".flac", ".ogg", ".oga", ".opus"}:
        audio = MutagenFile(path)
        if audio is None:
            return False
        if audio.tags is None:
            audio.add_tags()
        audio["LYRICS"] = [lyrics_text]
        audio["LYRICLANG"] = [language]
        if source:
            audio["LYRICS_SOURCE"] = [source]
        if source_id:
            audio["LYRICS_SOURCE_ID"] = [source_id]
        audio.save()
        return True

    if suffix == ".wav":
        audio = WAVE(path)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.delall("USLT")
        audio.tags.add(
            USLT(encoding=3, lang=language[:3] or "und", desc="Lyrics", text=lyrics_text)
        )
        for description, value in {
            "LYRICS_SOURCE": source,
            "LYRICS_SOURCE_ID": source_id,
        }.items():
            audio.tags.delall("TXXX:" + description)
            if value:
                audio.tags.add(TXXX(encoding=3, desc=description, text=[str(value)]))
        audio.save()
        return True

    LOGGER.info("Lyrics skipped for unsupported container: %s", suffix)
    return False
