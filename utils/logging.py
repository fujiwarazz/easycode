"""
Logging configuration for Easycode.

Provides structured logging with file and console output.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class EasycodeFormatter(logging.Formatter):
    """Custom formatter for Easycode logs."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def __init__(self, use_colors: bool = True, show_timestamps: bool = True):
        """Initialize formatter."""
        super().__init__()
        self.use_colors = use_colors
        self.show_timestamps = show_timestamps

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record."""
        # Build prefix
        parts = []

        if self.show_timestamps:
            timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
            parts.append(f"[{timestamp}]")

        level = record.levelname
        if self.use_colors and level in self.COLORS:
            level = f"{self.COLORS[level]}{level}{self.RESET}"
        parts.append(f"[{level}]")

        # Add component name if present
        if hasattr(record, "component"):
            parts.append(f"[{record.component}]")

        prefix = " ".join(parts)

        # Build message
        message = record.getMessage()

        # Add exception info if present
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)

        return f"{prefix} {message}"


class FileFormatter(logging.Formatter):
    """Formatter for log files (no colors)."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record for file output."""
        timestamp = datetime.fromtimestamp(record.created).isoformat()
        level = record.levelname.ljust(8)
        component = getattr(record, "component", "main").ljust(12)
        message = record.getMessage()

        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)

        return f"{timestamp} | {level} | {component} | {message}"


def setup_logging(
    config: Optional["Config"] = None,  # type: ignore
    level: Optional[str] = None,
    log_dir: Optional[Path] = None,
    show_timestamps: bool = True,
) -> logging.Logger:
    """
    Set up logging for Easycode.

    Args:
        config: Config object with logging settings.
        level: Log level override (DEBUG, INFO, WARNING, ERROR).
        log_dir: Directory for log files.
        show_timestamps: Whether to show timestamps in console output.

    Returns:
        Configured logger instance.
    """
    # Get or create logger
    logger = logging.getLogger("easycode")
    logger.setLevel(logging.DEBUG)  # Capture all, filter in handlers

    # Clear existing handlers
    logger.handlers.clear()

    # Determine settings
    if config:
        log_level = level or config.logging.level
        file_pattern = config.logging.file_pattern
        if log_dir is None and hasattr(config.workspace, "log_dir"):
            log_dir = config.workspace.log_dir
    else:
        log_level = level or "INFO"
        file_pattern = "easycode-{date}.log"

    log_level = log_level.upper()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level, logging.INFO))
    console_handler.setFormatter(EasycodeFormatter(use_colors=True, show_timestamps=show_timestamps))
    logger.addHandler(console_handler)

    # File handler
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / file_pattern.format(date=datetime.now().strftime("%Y-%m-%d"))

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # Always log everything to file
        file_handler.setFormatter(FileFormatter())
        logger.addHandler(file_handler)

    # Prevent propagation to root logger
    logger.propagate = False

    return logger


def get_logger(component: str) -> logging.Logger:
    """
    Get a logger with a component name.

    Args:
        component: Name of the component (e.g., "controller", "agent.claude").

    Returns:
        Logger instance with component context.
    """
    logger = logging.getLogger("easycode")

    # Create a wrapper that adds component context
    class ComponentLogger:
        def __init__(self, logger: logging.Logger, component: str):
            self._logger = logger
            self._component = component

        def _log(self, level: int, msg: str, *args, **kwargs):
            # Add component to extra
            extra = kwargs.get("extra", {})
            extra["component"] = self._component
            kwargs["extra"] = extra
            self._logger.log(level, msg, *args, **kwargs)

        def debug(self, msg: str, *args, **kwargs):
            self._log(logging.DEBUG, msg, *args, **kwargs)

        def info(self, msg: str, *args, **kwargs):
            self._log(logging.INFO, msg, *args, **kwargs)

        def warning(self, msg: str, *args, **kwargs):
            self._log(logging.WARNING, msg, *args, **kwargs)

        def error(self, msg: str, *args, **kwargs):
            self._log(logging.ERROR, msg, *args, **kwargs)

        def critical(self, msg: str, *args, **kwargs):
            self._log(logging.CRITICAL, msg, *args, **kwargs)

        def exception(self, msg: str, *args, **kwargs):
            kwargs["exc_info"] = True
            self._log(logging.ERROR, msg, *args, **kwargs)

    return ComponentLogger(logger, component)  # type: ignore