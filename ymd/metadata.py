"""Cross-format media tag writing.

The downloader used to contain separate, minimal MP3 and M4A branches.  This
module provides one normalized metadata model and supports common music-library
fields across MP3, M4A/MP4, FLAC, OGG/OPUS and WAV where the container permits
them.
"""

from __future__ import annotations

import json
import logging
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
    TDRC,
    TENC,
    TIT1,
    TIT2,
    TLAN,
    TPE1,
    TPE2,
    TPOS,
    TPUB,
    TRCK,
    TSRC,
    TXXX,
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
        "year": source.get("release_year") or (upload_date[:4] if upload_date else ""),
        "track": source.get("track_number"),
        "track_total": source.get("track_count"),
        "disc": source.get("disc_number"),
        "disc_total": source.get("disc_count"),
        "release_date": source.get("release_date"),
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
    if detected.get("webpage_url"):
        merged["source_url"] = detected["webpage_url"]
    return normalize_metadata(merged)


def _fraction(current: Any, total: Any) -> str:
    current_value = str(current or 0)
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
        "COMM",
    ):
        tags.delall(frame_id)

    _set_text(tags, TIT2, data.get("title"))
    _set_text(tags, TPE1, data.get("artist"))
    _set_text(tags, TALB, data.get("album"))
    _set_text(tags, TPE2, data.get("album_artist"))
    _set_text(tags, TDRC, data.get("year"))
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

    genre = data.get("genre")
    if genre not in ("", None):
        from mutagen.id3 import TCON

        _set_text(tags, TCON, genre)
    if data.get("comment"):
        tags.add(COMM(encoding=3, lang="eng", desc="", text=[str(data["comment"])]))

    custom_fields = {
        "SOURCE_URL": data.get("source_url"),
        "COMPILATION": "1" if data.get("compilation") else "",
        "ITUNESADVISORY": "1" if data.get("explicit") else "",
        **{field.upper(): _joined(data.get(field), limit=8000) for field in PROVENANCE_FIELDS},
        "RELEASE_TYPE": data.get("release_type"),
        "RELEASE_COUNTRY": data.get("release_country"),
        "RELEASE_STATUS": data.get("release_status"),
        "CATALOGNUMBER": data.get("catalog_number"),
        "BARCODE": data.get("barcode"),
        "MOOD": data.get("mood"),
    }
    for description, value in custom_fields.items():
        tags.delall("TXXX:" + description)
        if value:
            tags.add(TXXX(encoding=3, desc=description, text=[str(value)]))
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
        "\xa9day": data.get("year"),
        "\xa9gen": data.get("genre"),
        "\xa9wrt": data.get("composer"),
        "cprt": data.get("copyright"),
        "\xa9cmt": data.get("comment"),
        "\xa9grp": data.get("grouping"),
        "\xa9too": data.get("encoded_by"),
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
        "date": data.get("year"),
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
    data = normalize_metadata(metadata)
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
