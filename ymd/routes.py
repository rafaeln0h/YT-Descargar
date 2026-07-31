"""Flask blueprints for library playback and diagnostics."""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from .library import (
    build_library_catalog,
    clear_library_cache,
    media_mimetype,
    read_embedded_lyrics,
    read_media_artwork,
    resolve_media_path,
    scan_library,
)
from .updates import DEFAULT_REPOSITORY, check_latest_release
from .version import version_payload


def create_services_blueprint(
    config_loader: Callable[[], dict],
    *,
    log_path: str | Path,
) -> Blueprint:
    blueprint = Blueprint("ymd_services", __name__)
    application_log = Path(log_path).resolve()

    def library_root() -> Path:
        config = config_loader()
        return Path(config.get("download_path") or Path.home() / "Music" / "YouTube")

    @blueprint.get("/api/library")
    def library_index():
        config = config_loader()
        try:
            limit = int(request.args.get("limit", config.get("library_scan_limit", 250)))
        except (TypeError, ValueError):
            limit = 250
        items = scan_library(
            library_root(),
            limit=limit,
            query=request.args.get("q", ""),
        )
        catalog = build_library_catalog(items)
        return jsonify(
            {
                "root": str(library_root()),
                "root_exists": library_root().is_dir(),
                "count": len(items),
                "items": items,
                **catalog,
            }
        )

    @blueprint.post("/api/library/rescan")
    def library_rescan():
        root = library_root()
        clear_library_cache(root)
        config = config_loader()
        try:
            limit = int(config.get("library_scan_limit", 2000))
        except (TypeError, ValueError):
            limit = 2000
        items = scan_library(root, limit=max(limit, 2000))
        return jsonify(
            {
                "status": "ok",
                "root": str(root),
                "root_exists": root.is_dir(),
                "count": len(items),
                "items": items,
                **build_library_catalog(items),
            }
        )

    @blueprint.get("/api/library/media/<media_id>")
    def library_media(media_id: str):
        try:
            path = resolve_media_path(library_root(), media_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        # ``conditional`` gives browsers Range/206 support for seeking.
        return send_file(
            path,
            mimetype=media_mimetype(path),
            conditional=True,
            etag=True,
            max_age=0,
        )

    @blueprint.get("/api/library/artwork/<media_id>")
    def library_artwork(media_id: str):
        try:
            path = resolve_media_path(library_root(), media_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        cover = read_media_artwork(path)
        if not cover:
            return jsonify({"error": "Este archivo no tiene cover incrustado"}), 404
        data, mime = cover
        return send_file(
            io.BytesIO(data),
            mimetype=mime,
            conditional=True,
            etag=hashlib.sha256(data).hexdigest(),
            max_age=86400,
            download_name=f"{media_id}.jpg",
        )

    @blueprint.get("/api/library/lyrics/<media_id>")
    def library_lyrics(media_id: str):
        try:
            path = resolve_media_path(library_root(), media_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        lyrics = read_embedded_lyrics(path)
        if not lyrics:
            return jsonify({"error": "Este archivo no tiene letras incrustadas"}), 404
        return jsonify({"media_id": media_id, "lyrics": lyrics})

    @blueprint.get("/api/system/health")
    def system_health():
        config = config_loader()
        return jsonify(
            {
                "status": "ok",
                **version_payload(),
                "download_path": str(library_root()),
                "download_path_exists": library_root().exists(),
                "archive_enabled": config.get("use_download_archive", True),
                "logging": str(application_log),
            }
        )

    @blueprint.get("/api/system/capabilities")
    def system_capabilities():
        return jsonify(
            {
                **version_payload(),
                "features": {
                    "audio_download": True,
                    "video_download": True,
                    "playlists": True,
                    "mini_player": True,
                    "library_api": True,
                    "library_catalog": True,
                    "library_artwork": True,
                    "library_rescan": True,
                    "download_queue": True,
                    "github_release_updates": True,
                    "extended_metadata": True,
                    "metadata_sidecar": False,
                    "musicbrainz_enrichment": True,
                    "ytmusic_enrichment": True,
                    "acoustic_fingerprinting": True,
                    "discogs_enrichment": True,
                    "metadata_repair": True,
                    "replaygain_analysis": True,
                    "lyrics": True,
                    "subtitles": True,
                },
                "audio_formats": ["mp3", "m4a", "flac", "ogg", "opus", "wav"],
                "video_formats": ["mp4", "mkv"],
                "tag_containers": ["mp3", "m4a", "mp4", "flac", "ogg", "opus", "wav"],
                "metadata_sources": [
                    "yt-dlp",
                    "ytmusicapi",
                    "musicbrainz",
                    "acoustid",
                    "discogs",
                    "manual",
                ],
                "lyrics_sources": ["youtube_captions", "lrclib"],
                "current_platforms": ["windows", "linux", "macos"],
                "planned_platforms": ["android", "ios"],
            }
        )

    @blueprint.get("/api/system/update")
    def system_update():
        config = config_loader()
        current = version_payload()["version"]
        if config.get("check_for_updates", True) is False:
            return jsonify(
                {
                    "status": "disabled",
                    "current_version": current,
                    "update_available": False,
                }
            )
        try:
            interval = int(config.get("update_check_interval_hours", 12))
        except (TypeError, ValueError):
            interval = 12
        result = check_latest_release(
            current,
            repository=str(config.get("github_repository") or DEFAULT_REPOSITORY),
            interval_hours=interval,
            force=request.args.get("force", "").lower() in {"1", "true", "yes"},
        )
        return jsonify(result)

    @blueprint.get("/api/system/logs")
    def system_logs():
        try:
            limit = max(1, min(int(request.args.get("limit", 200)), 1000))
        except (TypeError, ValueError):
            limit = 200
        if not application_log.exists():
            return jsonify({"file": str(application_log), "lines": []})
        lines = application_log.read_text(encoding="utf-8", errors="replace").splitlines()
        return jsonify({"file": str(application_log), "lines": lines[-limit:]})

    return blueprint
