"""Shared logging setup helpers with colored output."""

from __future__ import annotations

import logging
import sys


class _AnsiLevelFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\x1b[36m",  # cyan
        logging.INFO: "\x1b[32m",  # green
        logging.WARNING: "\x1b[33m",  # yellow
        logging.ERROR: "\x1b[31m",  # red
        logging.CRITICAL: "\x1b[35m",  # magenta
    }
    RESET = "\x1b[0m"

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        color = self.COLORS.get(record.levelno, "")
        if not color:
            return base
        return f"{color}{base}{self.RESET}"


def configure_logging(*, debug: bool = False, force_color: bool = False) -> None:
    """Configure root logger with colored console output when available."""
    level = logging.DEBUG if debug else logging.INFO

    # Clear existing handlers so repeated script runs in-process don't duplicate logs.
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    use_rich = False
    stderr_encoding = (getattr(sys.stderr, "encoding", None) or "").lower()
    rich_safe = "utf" in stderr_encoding
    if (force_color or sys.stderr.isatty()) and rich_safe:
        try:
            from rich.logging import RichHandler

            handler = RichHandler(
                rich_tracebacks=True,
                show_path=False,
                show_time=True,
                omit_repeated_times=False,
                markup=False,
            )
            use_rich = True
        except Exception:
            handler = logging.StreamHandler()
    else:
        handler = logging.StreamHandler()

    if use_rich:
        formatter = logging.Formatter("%(message)s")
    elif force_color or sys.stderr.isatty():
        formatter = _AnsiLevelFormatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    handler.setFormatter(formatter)

    root.setLevel(level)
    root.addHandler(handler)
