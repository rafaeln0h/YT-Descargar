"""Optional local audio measurements; no catalogue data is inferred here."""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any


def parse_loudnorm_output(output: str, *, target_lufs: float = -18.0) -> dict[str, Any]:
    blocks = re.findall(r"\{[^{}]+\}", output or "", flags=re.DOTALL)
    for raw in reversed(blocks):
        try:
            payload = json.loads(raw)
            integrated = float(payload["input_i"])
            true_peak_db = float(payload["input_tp"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        gain = target_lufs - integrated
        peak_linear = math.pow(10.0, true_peak_db / 20.0)
        return {
            "replaygain_track_gain": f"{gain:+.2f} dB",
            "replaygain_track_peak": f"{peak_linear:.8f}",
            "loudness_integrated": f"{integrated:.2f} LUFS",
            "true_peak": f"{true_peak_db:.2f} dBTP",
            "audio_analysis_source": "ffmpeg_loudnorm",
        }
    return {}


def analyze_loudness(
    file_path: str | Path,
    *,
    ffmpeg_path: str | Path = "ffmpeg",
    timeout: int = 300,
    target_lufs: float = -18.0,
) -> dict[str, Any]:
    """Measure loudness and expose ReplayGain-compatible track fields."""

    path = Path(file_path)
    if not path.is_file():
        return {"audio_analysis_status": "file_missing"}
    command = [
        str(ffmpeg_path),
        "-nostdin",
        "-hide_banner",
        "-i",
        str(path),
        "-af",
        f"loudnorm=I={target_lufs}:TP=-1.0:LRA=11:print_format=json",
        "-f",
        "null",
        "NUL",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"audio_analysis_status": "unavailable", "audio_analysis_error": str(exc)[:500]}
    measured = parse_loudnorm_output(completed.stderr, target_lufs=target_lufs)
    if not measured:
        return {
            "audio_analysis_status": "failed",
            "audio_analysis_error": completed.stderr[-500:],
        }
    measured["audio_analysis_status"] = "complete"
    return measured
