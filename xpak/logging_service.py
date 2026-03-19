from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_DIR = Path.home() / ".local" / "state" / "xpak" / "logs"
LOG_FILE = LOG_DIR / "xpak.log"
MAX_LOG_BYTES = 1024 * 1024
BACKUP_COUNT = 4


def get_log_dir() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR


def get_log_file() -> Path:
    get_log_dir()
    return LOG_FILE


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("xpak")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    handler = RotatingFileHandler(
        get_log_file(),
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    return logger


def get_logger(name: str = "xpak") -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)


def install_exception_hooks():
    logger = get_logger("xpak.exceptions")

    def _log_unhandled(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.exception(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = _log_unhandled
