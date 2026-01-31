"""Structured logging setup."""

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import structlog


def setup_logging(level: str = "INFO", log_name: str | None = None) -> structlog.BoundLogger:
    """Configure structured logging.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        log_name: Optional name for file logging (e.g., "gateway", "aggregator").
                  If provided, logs will be written to logs/{log_name}.log with
                  daily rotation at midnight, keeping 30 days of backups.

    Returns:
        Configured logger
    """
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper()),
    )

    # Add file handler if log_name provided
    if log_name:
        log_dir = Path(__file__).parent.parent.parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)

        file_handler = TimedRotatingFileHandler(
            log_dir / f"{log_name}.log",
            when="midnight",
            backupCount=30,
        )
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        file_handler.setLevel(getattr(logging, level.upper()))
        logging.getLogger().addHandler(file_handler)

    return structlog.get_logger()


def get_logger(name: str = __name__) -> structlog.BoundLogger:
    """Get a logger instance.

    Args:
        name: Logger name

    Returns:
        Logger instance
    """
    return structlog.get_logger(name)
