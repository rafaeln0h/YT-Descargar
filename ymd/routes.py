"""Flask blueprints for library playback and diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from .library import media_mimetype, resolve_media_path, scan_library
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
        return jsonify(
            {
                "root": str(library_root()),
                "count": len(items),
                "items": items,
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
                    "download_queue": True,
                    "extended_metadata": True,
                    "metadata_sidecar": False,
                    "musicbrainz_enrichment": True,
                    "lyrics": True,
                    "subtitles": True,
                },
                "audio_formats": ["mp3", "m4a", "flac", "ogg", "opus", "wav"],
                "video_formats": ["mp4", "mkv"],
                "tag_containers": ["mp3", "m4a", "mp4", "flac", "ogg", "opus", "wav"],
                "metadata_sources": ["yt-dlp", "musicbrainz", "manual"],
                "lyrics_sources": ["youtube_captions", "lrclib"],
                "current_platforms": ["windows", "linux", "macos"],
                "planned_platforms": ["android", "ios"],
            }
        )

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
