"""Application logging with rotation and useful context."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s | "
    "%(threadName)s | %(message)s"
)


def setup_logging(
    log_dir: str | Path = "logs",
    *,
    level: int | str = logging.INFO,
) -> Path:
    """Configure console and rotating-file logging once.

    Returns the absolute log path so the diagnostics API and documentation can
    point to the same file.
    """

    directory = Path(log_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / "ymd.log"

    root = logging.getLogger()
    root.setLevel(level)
    if any(getattr(handler, "_ymd_handler", False) for handler in root.handlers):
        return log_path

    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler._ymd_handler = True  # type: ignore[attr-defined]

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler._ymd_handler = True  # type: ignore[attr-defined]

    root.addHandler(file_handler)
    root.addHandler(console_handler)
    return log_path


class YTDLPLogger:
    """Bridge yt-dlp messages into the application's rotating logs."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("ymd.yt_dlp")

    def debug(self, message: str) -> None:
        # yt-dlp sometimes sends informational lines through ``debug``.
        self.logger.debug(message)

    def warning(self, message: str) -> None:
        self.logger.warning(message)

    def error(self, message: str) -> None:
        self.logger.error(message)

