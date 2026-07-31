"""CLI seguro para planificar o aplicar la reorganizacion de la biblioteca."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ymd.repair import repair_library, rollback_library_repair  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reorganiza medios como Artista/Año - Álbum/01 - Canción. "
            "El modo predeterminado es una simulacion sin mover ni reetiquetar archivos."
        )
    )
    parser.add_argument("root", type=Path, help="Raiz exacta de la biblioteca")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aplica el plan. Sin esta opcion solo se genera un dry-run.",
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Consulta MusicBrainz para completar campos verificables; nunca agrega genero.",
    )
    parser.add_argument(
        "--analyze-audio",
        action="store_true",
        help="Calcula loudness/ReplayGain localmente con FFmpeg (puede tardar varios minutos).",
    )
    parser.add_argument(
        "--ffmpeg",
        type=Path,
        default=PROJECT_ROOT / "ffmpeg_portable" / "bin" / "ffmpeg.exe",
        help="Ruta al ejecutable FFmpeg usado por --analyze-audio.",
    )
    parser.add_argument("--journal", type=Path, help="Ruta opcional del journal JSON de salida")
    parser.add_argument(
        "--rollback",
        type=Path,
        metavar="JOURNAL_APPLY",
        help="Revierte los movimientos completados del journal indicado.",
    )
    return parser


def _print_result(result: dict) -> None:
    summary = result.get("summary") or {}
    print(f"Estado: {result.get('status', 'desconocido')}")
    print(f"Raiz: {result.get('root', '')}")
    print(f"Journal: {result.get('journal_path', '')}")
    print("Resumen: " + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    if result.get("mode") == "dry-run":
        print("Simulacion terminada: no se movio ni reetiqueto ningun archivo.")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.rollback and (args.apply or args.enrich or args.analyze_audio):
        parser.error("--rollback no se combina con --apply, --enrich ni --analyze-audio")
    try:
        if args.rollback:
            result = rollback_library_repair(
                args.root,
                args.rollback,
                journal_path=args.journal,
            )
        else:
            result = repair_library(
                args.root,
                apply=args.apply,
                enrich=args.enrich,
                journal_path=args.journal,
                analyze_audio=args.analyze_audio,
                ffmpeg_path=args.ffmpeg,
            )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    _print_result(result)
    return 1 if result.get("status") == "completed_with_errors" else 0


if __name__ == "__main__":
    raise SystemExit(main())
