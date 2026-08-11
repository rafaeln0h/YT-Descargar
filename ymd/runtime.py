"""Runtime discovery and yt-dlp option helpers."""

from __future__ import annotations

import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

SUPPORTED_JS_RUNTIMES = ("deno", "node")
LEGACY_PLAYER_CLIENTS = {"default,web_music", "web_music,default"}


def package_version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return ""


def find_executable(name: str) -> str:
    executable = f"{name}.exe" if sys.platform == "win32" else name
    candidates = [Path(sys.executable).resolve().parent / executable]
    discovered = shutil.which(name)
    if discovered:
        candidates.append(Path(discovered))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    return ""


def executable_version(path: str, *args: str) -> str:
    if not path:
        return ""
    try:
        result = subprocess.run(
            [path, *args],
            capture_output=True,
            check=False,
            text=True,
            timeout=4,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    output = (result.stdout or result.stderr).strip().splitlines()
    return output[0].strip() if output else ""


def normalize_player_client(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized or normalized.casefold() in LEGACY_PLAYER_CLIENTS:
        return "auto"
    return normalized


def youtube_extractor_args(config: dict) -> dict:
    raw_value = normalize_player_client(config.get("youtube_player_client"))
    clients = [item.strip() for item in raw_value.split(",") if item.strip()]
    if not clients or any(item.casefold() == "auto" for item in clients):
        return {}
    return {"youtube": {"player_client": clients}}


def detect_js_runtime(preference: object = "auto") -> dict:
    requested = str(preference or "auto").strip().casefold()
    if requested == "none":
        return {"requested": requested, "name": "", "path": "", "version": ""}

    names = SUPPORTED_JS_RUNTIMES if requested == "auto" else (requested,)
    for name in names:
        if name not in SUPPORTED_JS_RUNTIMES:
            continue
        path = find_executable(name)
        if path:
            version_arg = "--version"
            return {
                "requested": requested,
                "name": name,
                "path": path,
                "version": executable_version(path, version_arg),
            }
    return {"requested": requested, "name": "", "path": "", "version": ""}


def yt_dlp_runtime_options(config: dict) -> dict:
    runtime = detect_js_runtime(config.get("youtube_js_runtime", "auto"))
    if not runtime["name"]:
        return {"js_runtimes": {}}
    return {
        "js_runtimes": {
            runtime["name"]: {"path": runtime["path"]},
        }
    }


def runtime_diagnostics(config: dict, *, ffmpeg_path: str | Path | None = None) -> dict:
    selected = detect_js_runtime(config.get("youtube_js_runtime", "auto"))
    runtimes = []
    for name in SUPPORTED_JS_RUNTIMES:
        path = find_executable(name)
        runtimes.append(
            {
                "name": name,
                "available": bool(path),
                "path": path,
                "version": executable_version(path, "--version") if path else "",
                "selected": name == selected["name"],
            }
        )

    ffmpeg_root = Path(ffmpeg_path).resolve() if ffmpeg_path else None
    if ffmpeg_root and ffmpeg_root.is_dir():
        suffix = ".exe" if sys.platform == "win32" else ""
        ffmpeg = ffmpeg_root / f"ffmpeg{suffix}"
        ffprobe = ffmpeg_root / f"ffprobe{suffix}"
    else:
        ffmpeg = Path(shutil.which("ffmpeg") or "")
        ffprobe = Path(shutil.which("ffprobe") or "")

    ffmpeg_value = str(ffmpeg) if ffmpeg.is_file() else ""
    ffprobe_value = str(ffprobe) if ffprobe.is_file() else ""
    ejs_version = package_version("yt-dlp-ejs")
    warnings = []
    if not selected["name"]:
        warnings.append("No hay un runtime JavaScript habilitado y disponible.")
    if not ejs_version:
        warnings.append("Falta yt-dlp-ejs para el soporte completo de YouTube.")
    if not ffmpeg_value or not ffprobe_value:
        warnings.append("FFmpeg o ffprobe no están disponibles.")

    provider_packages = ("bgutil-ytdlp-pot-provider", "yt-dlp-getpot-wpc")
    providers = [
        {"name": name, "version": package_version(name)}
        for name in provider_packages
        if package_version(name)
    ]
    return {
        "status": "ready" if not warnings else "degraded",
        "python": {
            "version": ".".join(str(value) for value in sys.version_info[:3]),
            "executable": sys.executable,
        },
        "yt_dlp": {
            "version": package_version("yt-dlp"),
            "ejs_version": ejs_version,
            "curl_cffi_version": package_version("curl-cffi"),
        },
        "javascript": {
            "requested": selected["requested"],
            "selected": selected["name"],
            "runtimes": runtimes,
        },
        "ffmpeg": {
            "available": bool(ffmpeg_value),
            "path": ffmpeg_value,
            "version": executable_version(ffmpeg_value, "-version") if ffmpeg_value else "",
            "ffprobe_available": bool(ffprobe_value),
            "ffprobe_path": ffprobe_value,
        },
        "youtube": {
            "player_client": normalize_player_client(config.get("youtube_player_client")),
            "po_token_provider": providers,
        },
        "warnings": warnings,
    }
