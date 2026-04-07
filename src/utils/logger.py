from __future__ import annotations

import logging


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: str = "INFO") -> None:
    resolved_level = getattr(logging, level.upper(), logging.INFO)
    root_logger = logging.getLogger()

    if not root_logger.handlers:
        logging.basicConfig(
            level=resolved_level,
            format=LOG_FORMAT,
            datefmt=DATE_FORMAT,
        )

    root_logger.setLevel(resolved_level)

    # TODO(v0.2): optionally add file logging under data/logs when needed.


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
