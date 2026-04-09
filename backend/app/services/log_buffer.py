"""In-memory rotating log buffer for the web UI error log viewer.

Captures all Python log records into a bounded deque so operators can
inspect recent application logs directly from the browser without needing
SSH access or file system access to the container.

Usage:
    Call install_memory_handler() once at application startup (before the
    lifespan yields) to attach the handler to the root logger.

    Call get_recent_logs(n) from route handlers to retrieve the last n
    log entries (newest first) as JSON-serializable dicts.
"""
import collections
import logging
import threading
from typing import List

# Thread-safe bounded buffer: newest entries are at index 0 (appendleft)
_MAX_ENTRIES = 500
_log_buffer: collections.deque = collections.deque(maxlen=_MAX_ENTRIES)
_buffer_lock = threading.Lock()


class MemoryLogHandler(logging.Handler):
    """A logging.Handler that appends formatted records to the in-memory deque."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "ts": self.formatter.formatTime(record, "%Y-%m-%d %H:%M:%S")
                if self.formatter
                else record.asctime,
                "level": record.levelname,
                "name": record.name,
                "msg": (self.format(record) if self.formatter else record.getMessage())[:4096],
            }
            with _buffer_lock:
                _log_buffer.appendleft(entry)
        except Exception:
            # Never let the log handler itself crash the application
            self.handleError(record)


def install_memory_handler() -> None:
    """
    Attach a MemoryLogHandler to the root logger.

    Must be called before any other startup code so that startup log messages
    are captured in the buffer and visible in the web UI log viewer.
    """
    handler = MemoryLogHandler()
    formatter = logging.Formatter(
        fmt="%(asctime)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    handler.setLevel(logging.DEBUG)

    root_logger = logging.getLogger()
    # Avoid duplicate handlers if called more than once (e.g., during reload)
    existing_types = {type(h) for h in root_logger.handlers}
    if MemoryLogHandler not in existing_types:
        root_logger.addHandler(handler)


def get_recent_logs(n: int = 200) -> List[dict]:
    """
    Return the most recent n log entries, newest first.

    Args:
        n: Maximum number of entries to return (capped at _MAX_ENTRIES).
    """
    n = min(max(1, n), _MAX_ENTRIES)
    with _buffer_lock:
        return list(_log_buffer)[:n]
