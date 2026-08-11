"""Optional YouTube Music album enrichment through ``ytmusicapi``.

The dependency is intentionally optional.  This module never authenticates and
only operates when an album browse ID, or an official album playlist ID that
can be converted to one, is already present in extractor metadata.
"""

from __future__ import annotations

import importlib
import logging
import re
import unicodedata
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

LOGGER = logging.getLogger(__name__)


def _normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _provider_result(
    fields: Mapping[str, Any],
    *,
    confidence: float = 0,
    reference: str = "",
    status: str = "ok",
    reason: str = "",
) -> dict[str, Any]:
    return {
        "provider": "ytmusicapi",
        "status": status,
        "fields": {key: value for key, value in dict(fields).items() if value not in ("", None, [])},
        "confidence": round(max(0.0, min(float(confidence), 1.0)), 3),
        "reference": reference,
        "reason": reason,
    }


def _official_playlist_id(metadata: Mapping[str, Any]) -> str:
    for key in ("playlist_id", "playlistId"):
        value = str(metadata.get(key) or "").strip()
        if value.startswith(("OLAK5uy_", "RDAMPLOLAK5uy_")):
            return value
    for key in ("playlist_url", "webpage_url", "source_url"):
        value = str(metadata.get(key) or "").strip()
        if not value:
            continue
        playlist_id = (parse_qs(urlparse(value).query).get("list") or [""])[0]
        if playlist_id.startswith(("OLAK5uy_", "RDAMPLOLAK5uy_")):
            return playlist_id
    return ""


def extract_album_browse_id(metadata: Mapping[str, Any]) -> str:
    for key in ("album_browse_id", "browse_id", "browseId"):
        value = str(metadata.get(key) or "").strip()
        if value.startswith("MPRE"):
            return value
    return ""


def _load_client() -> Any | None:
    try:
        module = importlib.import_module("ytmusicapi")
    except ImportError:
        return None
    return module.YTMusic()


def _artist_names(value: Any) -> list[str]:
    names: list[str] = []
    for artist in value or []:
        if isinstance(artist, dict) and artist.get("name"):
            names.append(str(artist["name"]))
        elif isinstance(artist, str) and artist:
            names.append(artist)
    return names


def _best_thumbnail(value: Any) -> str:
    thumbnails = value if isinstance(value, list) else []
    valid = [item for item in thumbnails if isinstance(item, dict) and item.get("url")]
    if not valid:
        return ""
    return str(max(valid, key=lambda item: (item.get("width") or 0) * (item.get("height") or 0))["url"])


def _section_results(client: Any, section: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    preview = [item for item in section.get("results") or [] if isinstance(item, dict)]
    browse_id = str(section.get("browseId") or "")
    params = str(section.get("params") or "")
    if browse_id and params and hasattr(client, "get_artist_albums"):
        try:
            complete = client.get_artist_albums(browse_id, params)
            if isinstance(complete, list) and complete:
                return [item for item in complete if isinstance(item, dict)]
        except Exception as exc:
            LOGGER.info("YouTube Music artist section could not be expanded: %s", exc)
    return preview


def _catalog_item(row: Mapping[str, Any], artist: str, default_type: str) -> dict[str, Any]:
    playlist_id = str(row.get("playlistId") or row.get("audioPlaylistId") or "")
    release_type = str(row.get("type") or default_type).strip() or default_type
    normalized_type = _normalized(release_type)
    if normalized_type == "album":
        category = "album"
    elif normalized_type in {"ep", "e p"}:
        category = "ep"
    elif normalized_type in {"single", "sencillo"}:
        category = "single"
    else:
        category = "collection"
    return {
        "id": playlist_id or str(row.get("browseId") or ""),
        "title": str(row.get("title") or "Lanzamiento"),
        "artist": artist,
        "album_artist": artist,
        "album": str(row.get("title") or ""),
        "year": str(row.get("year") or ""),
        "thumbnail": _best_thumbnail(row.get("thumbnails")),
        "url": f"https://music.youtube.com/playlist?list={playlist_id}" if playlist_id else "",
        "item_type": "collection",
        "collection_kind": "official_album",
        "release_type": release_type,
        "category": category,
        "source": "ytmusic_catalog",
        "selected_by_default": True,
        "explicit": bool(row.get("isExplicit")) if row.get("isExplicit") is not None else None,
    }


def discover_ytmusic_artist_catalog(
    *,
    artist_name: str = "",
    artist_browse_id: str = "",
    channel_id: str = "",
    client: Any | None = None,
) -> dict[str, Any]:
    """Discover the complete public album/single/EP catalog for an artist.

    This uses unauthenticated ytmusicapi calls.  A channel ID is used to verify
    search results when available so that an artist with a similar name is not
    silently selected.
    """

    resolved_client = client or _load_client()
    if resolved_client is None:
        return {"status": "unavailable", "artist": artist_name, "items": []}

    browse_id = str(artist_browse_id or "").strip()
    if browse_id.startswith("MPADUC"):
        browse_id = browse_id[4:]

    try:
        profile: Mapping[str, Any] = {}
        if browse_id.startswith("UC"):
            candidate = resolved_client.get_artist(browse_id)
            if isinstance(candidate, dict):
                profile = candidate
        else:
            results = resolved_client.search(artist_name, filter="artists", limit=10)
            exact = [
                item
                for item in (results or [])
                if isinstance(item, dict) and _normalized(item.get("artist")) == _normalized(artist_name)
            ]
            for result in exact:
                candidate_id = str(result.get("browseId") or "")
                if not candidate_id:
                    continue
                candidate = resolved_client.get_artist(candidate_id)
                if not isinstance(candidate, dict):
                    continue
                if channel_id and str(candidate.get("channelId") or "") != str(channel_id):
                    continue
                browse_id = candidate_id
                profile = candidate
                break

        if not profile:
            return {"status": "not_found", "artist": artist_name, "items": []}

        resolved_artist = str(profile.get("name") or artist_name or "Unknown")
        items: list[dict[str, Any]] = []
        for section_name, default_type in (("albums", "Album"), ("singles", "Single")):
            section = profile.get(section_name) or {}
            if not isinstance(section, dict):
                continue
            for row in _section_results(resolved_client, section):
                item = _catalog_item(row, resolved_artist, default_type)
                if item.get("url"):
                    items.append(item)

        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            key = str(item.get("url") or item.get("id") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(item)

        breakdown: dict[str, int] = {"album": 0, "single": 0, "ep": 0}
        for item in deduped:
            category = str(item.get("category") or "collection")
            breakdown[category] = breakdown.get(category, 0) + 1

        return {
            "status": "ok",
            "artist": resolved_artist,
            "artist_browse_id": browse_id,
            "releases_browse_id": str((profile.get("albums") or {}).get("browseId") or ""),
            "thumbnail": _best_thumbnail(profile.get("thumbnails")),
            "items": deduped,
            "breakdown": breakdown,
        }
    except Exception as exc:
        LOGGER.warning("ytmusicapi artist catalog lookup failed for %s: %s", artist_name or browse_id, exc)
        return {
            "status": "error",
            "artist": artist_name,
            "items": [],
            "reason": type(exc).__name__,
        }


def _pick_track(album: Mapping[str, Any], metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    tracks = [item for item in album.get("tracks") or [] if isinstance(item, dict)]
    youtube_id = str(metadata.get("youtube_id") or "")
    if youtube_id:
        for track in tracks:
            if str(track.get("videoId") or "") == youtube_id:
                return track
    wanted_title = _normalized(metadata.get("title"))
    wanted_artist = _normalized(metadata.get("artist"))
    if not wanted_title:
        return {}
    for track in tracks:
        if _normalized(track.get("title")) != wanted_title:
            continue
        track_artists = {_normalized(name) for name in _artist_names(track.get("artists"))}
        if not wanted_artist or wanted_artist in track_artists:
            return track
    return {}


def parse_ytmusic_album(
    album: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Return only fields exposed directly by ytmusicapi album data."""

    album_artists = _artist_names(album.get("artists"))
    track = _pick_track(album, metadata)
    track_artists = _artist_names(track.get("artists"))
    tracks = [item for item in album.get("tracks") or [] if isinstance(item, dict)]
    fields: dict[str, Any] = {
        "album": album.get("title", ""),
        "album_artist": "; ".join(album_artists),
        "artist": "; ".join(track_artists),
        "year": album.get("year", ""),
        "release_type": album.get("type", ""),
        "track_total": album.get("trackCount") or len(tracks) or "",
    }
    explicit = track.get("isExplicit") if track else album.get("isExplicit")
    if explicit is not None:
        fields["explicit"] = bool(explicit)
        fields["explicit_known"] = True
    if track:
        try:
            fields["track"] = tracks.index(track) + 1
        except ValueError:
            pass
    # ytmusicapi does not expose dependable songwriter/producer credits in
    # get_album; deliberately leave credits unavailable instead of guessing.
    return {key: value for key, value in fields.items() if value not in ("", None, [])}


def parse_ytmusic_credits(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Map the credit sections YouTube Music exposes without guessing roles."""

    def names(section: str) -> list[str]:
        value = payload.get(section) or {}
        data = value.get("data") if isinstance(value, dict) else []
        return [str(item).strip() for item in (data or []) if str(item).strip()]

    performed = names("performed_by")
    written = names("written_by")
    produced = names("produced_by")
    providers = names("music_metadata_provided_by")
    other = []
    for section in payload.get("other_sections") or []:
        if not isinstance(section, dict):
            continue
        role = str(section.get("localized_title") or "credit").strip()
        for person in section.get("data") or []:
            if str(person).strip():
                other.append({"role": role, "name": str(person).strip()})
    fields = {
        "performers": "; ".join(dict.fromkeys(performed)),
        "composer": "; ".join(dict.fromkeys(written)),
        "written_by": "; ".join(dict.fromkeys(written)),
        "producer": "; ".join(dict.fromkeys(produced)),
        "metadata_provider": "; ".join(dict.fromkeys(providers)),
        "credits": other,
        "credits_source": "youtube_music",
    }
    return {key: value for key, value in fields.items() if value not in ("", None, [])}


def lookup_ytmusic_album(
    metadata: Mapping[str, Any],
    *,
    client: Any | None = None,
) -> dict[str, Any]:
    browse_id = extract_album_browse_id(metadata)
    playlist_id = _official_playlist_id(metadata)
    if not browse_id and not playlist_id:
        return _provider_result(
            {},
            status="not_applicable",
            reason="No official album browse ID or playlist ID",
        )
    resolved_client = client or _load_client()
    if resolved_client is None:
        return _provider_result(
            {},
            status="unavailable",
            reason="Optional dependency ytmusicapi is not installed",
        )
    try:
        if not browse_id and playlist_id:
            browse_id = str(resolved_client.get_album_browse_id(playlist_id) or "")
        if not browse_id:
            return _provider_result(
                {},
                status="not_found",
                reason="Official playlist could not be resolved to an album",
            )
        album = resolved_client.get_album(browse_id)
        if not isinstance(album, dict) or not album:
            return _provider_result({}, status="not_found", reason="Album payload was empty")
        fields = parse_ytmusic_album(album, metadata)
        track = _pick_track(album, metadata)
        credits_browse_id = str(track.get("creditsBrowseId") or "") if track else ""
        if credits_browse_id and hasattr(resolved_client, "get_song_credits"):
            try:
                credits = resolved_client.get_song_credits(credits_browse_id)
                if isinstance(credits, dict):
                    fields.update(parse_ytmusic_credits(credits))
            except Exception as exc:
                LOGGER.info("YouTube Music credits unavailable for %s: %s", credits_browse_id, exc)
        return _provider_result(fields, confidence=0.96, reference=browse_id)
    except Exception as exc:
        LOGGER.warning("ytmusicapi album lookup failed for %s: %s", browse_id or playlist_id, exc)
        return _provider_result(
            {},
            status="error",
            reference=browse_id or playlist_id,
            reason=type(exc).__name__,
        )
