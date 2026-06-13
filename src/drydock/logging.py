"""Standard logging configuration for Drydock — run logger and per-execution logger."""

from __future__ import annotations

import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

_RUN_LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
_RUN_LOG_BACKUP_COUNT = 5  # keep run.log + 5 rotated copies


def setup_run_logger(log_file: Path, *, debug: bool = False) -> None:
    """Attach a rotating file handler (and optional stderr handler) to the drydock root logger.

    All modules that use ``logging.getLogger(__name__)`` under the ``drydock.*``
    hierarchy automatically inherit these handlers. ``--debug`` also routes DEBUG
    lines to stderr so they appear in the terminal alongside normal output.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("drydock")
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)sZ  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    fmt.converter = time.gmtime

    fh = RotatingFileHandler(
        log_file,
        maxBytes=_RUN_LOG_MAX_BYTES,
        backupCount=_RUN_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    if debug:
        sh = logging.StreamHandler(sys.stderr)
        sh.setLevel(logging.DEBUG)
        sh.setFormatter(logging.Formatter("%(levelname)-7s  %(name)s  %(message)s"))
        root.addHandler(sh)


def create_execution_logger(
    execution_id: str,
    log_file: Path,
    *,
    debug: bool,
) -> logging.Logger:
    logger = logging.getLogger(f"drydock.execution.{execution_id}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)sZ %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logger.handlers.clear()
    logger.addHandler(file_handler)

    if debug:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    return logger


def close_execution_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
