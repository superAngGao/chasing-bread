"""Logging configuration utilities."""

from __future__ import annotations

import logging
import sys


def configure_logging(
    level: str = "INFO",
    debug: bool = False,
) -> None:
    """Set up root logger with coloured level names when running in a terminal."""
    effective_level = "DEBUG" if debug else level.upper()

    root = logging.getLogger()
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(getattr(logging, effective_level, logging.INFO))
