"""Privacy-preserving logging helpers for VietClean applications.

The module deliberately emits only a small, stable set of fields.  Messages,
arguments and exception text are redacted immediately before formatting so the
same protection applies at ``DEBUG`` and higher levels.  Callers should still
log aggregate metadata rather than row or cell values.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import sys
from typing import IO, Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4


LogFormat = Literal["text", "json"]

_LOGGER_NAME = "vietclean"
_RUN_ID: ContextVar[str] = ContextVar("vietclean_run_id", default="-")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\]\[(){}<>]+")
_EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9])[A-Za-z0-9._%+-]*@"
    r"([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)"
)
_PHONE_OR_ACCOUNT_RE = re.compile(r"(?<!\w)(?:\+?\d[\d .()/-]{7,}\d)(?!\w)")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|secret[_-]?key|private[_-]?key|aws[_-]?access[_-]?key[_-]?id|"
    r"aws[_-]?secret[_-]?access[_-]?key|password|passwd|pwd|secret|username|user[_-]?id|"
    r"uid|connection[_-]?string|database[_-]?url|dsn)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_AUTHORIZATION_VALUE_RE = re.compile(
    r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+"
)
_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def new_run_id() -> str:
    """Return a random non-identifying run identifier."""

    return uuid4().hex


def set_run_id(run_id: str | None = None) -> str:
    """Set and return the correlation ID used by subsequent log records."""

    selected = new_run_id() if run_id is None else run_id
    if not isinstance(selected, str) or not _RUN_ID_RE.fullmatch(selected):
        raise ValueError("run_id phải có 1-64 ký tự chữ, số, dấu '.', '_' hoặc '-'.")
    _RUN_ID.set(selected)
    return selected


def get_run_id() -> str:
    """Return the correlation ID in the current execution context."""

    return _RUN_ID.get()


def _redact_url(match: re.Match[str]) -> str:
    candidate = match.group(0)
    trailing = ""
    while candidate and candidate[-1] in ".,;:!?\"'":
        trailing = candidate[-1] + trailing
        candidate = candidate[:-1]
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return "[REDACTED-URL]" + trailing

    hostname = parts.hostname or ""
    if not hostname:
        return f"{parts.scheme}://[REDACTED]" + trailing
    host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    try:
        port = f":{parts.port}" if parts.port is not None else ""
    except ValueError:
        port = ""
    userinfo = "***@" if parts.username is not None or parts.password is not None else ""
    # ``urlunsplit`` omits ``//`` for schemes not registered in urllib's
    # legacy ``uses_netloc`` table (for example postgresql). Build the safe
    # authority explicitly after the parser has validated its components.
    safe = f"{parts.scheme}://{userinfo}{host}{port}{parts.path}"
    return safe + trailing


def _redact_number(match: re.Match[str]) -> str:
    value = match.group(0)
    digits = re.sub(r"\D", "", value)
    if not 9 <= len(digits) <= 19:
        return value
    return f"***{digits[-4:]}"


def redact_log_text(value: object) -> str:
    """Return log-safe text with common credential and PII forms masked.

    This is a last line of defence, not permission to log customer data.  The
    pipeline should emit aggregate counts, column names and rule identifiers.
    Newlines and tabs are escaped to prevent forged multi-line log entries.
    """

    text = str(value)
    text = _URL_RE.sub(_redact_url, text)
    text = _AUTHORIZATION_VALUE_RE.sub(lambda item: f"{item.group(1)} ***", text)
    text = _SECRET_ASSIGNMENT_RE.sub(lambda item: f"{item.group(1)}{item.group(2)}***", text)
    text = _EMAIL_RE.sub(lambda item: f"{item.group(1)}***@{item.group(2)}", text)
    text = _PHONE_OR_ACCOUNT_RE.sub(_redact_number, text)
    return text.replace("\r", r"\r").replace("\n", r"\n").replace("\t", r"\t")


class _RunContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.vietclean_run_id = get_run_id()
        return True


class SafeTextFormatter(logging.Formatter):
    """Single-line UTC text formatter that redacts message and traceback."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, timezone.utc).isoformat()
        message = redact_log_text(record.getMessage())
        run_id = redact_log_text(getattr(record, "vietclean_run_id", get_run_id()))
        rendered = (
            f"{timestamp} level={record.levelname} logger={redact_log_text(record.name)} "
            f"run_id={run_id} message={message}"
        )
        if record.exc_info:
            rendered += " exception=" + redact_log_text(self.formatException(record.exc_info))
        return rendered


class SafeJsonFormatter(logging.Formatter):
    """JSON Lines formatter with an allowlisted, privacy-safe schema."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, str] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": redact_log_text(record.name),
            "run_id": redact_log_text(getattr(record, "vietclean_run_id", get_run_id())),
            "message": redact_log_text(record.getMessage()),
        }
        if record.exc_info:
            payload["exception"] = redact_log_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class LoggingContext:
    """Configured logger and its non-identifying correlation ID."""

    logger: logging.Logger
    run_id: str


def _parse_level(level: str | int) -> int:
    if isinstance(level, bool):
        raise ValueError("log level phải là DEBUG, INFO, WARNING hoặc ERROR.")
    if isinstance(level, int):
        if level in _LEVELS.values():
            return level
        raise ValueError("log level dạng số không được hỗ trợ.")
    if not isinstance(level, str) or level.upper() not in _LEVELS:
        raise ValueError("log level phải là DEBUG, INFO, WARNING, ERROR hoặc CRITICAL.")
    return _LEVELS[level.upper()]


def _formatter(log_format: LogFormat) -> logging.Formatter:
    if log_format == "text":
        return SafeTextFormatter()
    if log_format == "json":
        return SafeJsonFormatter()
    raise ValueError("log_format phải là 'text' hoặc 'json'.")


def reset_logging() -> None:
    """Close handlers installed on the VietClean logger, primarily for tests."""

    logger = logging.getLogger(_LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.propagate = False
    logger.disabled = False


def configure_logging(
    *,
    level: str | int = "INFO",
    log_file: str | Path | None = None,
    log_format: LogFormat = "text",
    run_id: str | None = None,
    console: bool = True,
    stream: IO[str] | None = None,
) -> LoggingContext:
    """Configure privacy-safe VietClean logging without changing the root logger.

    Reconfiguration replaces and closes only handlers previously attached to
    the ``vietclean`` logger.  File logs are UTF-8 and append-only so an earlier
    run is never silently destroyed.
    """

    if not isinstance(console, bool):
        raise TypeError("console phải là true hoặc false.")
    selected_level = _parse_level(level)
    selected_formatter = _formatter(log_format)
    selected_run_id = set_run_id(run_id)
    reset_logging()

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(selected_level)
    logger.propagate = False
    context_filter = _RunContextFilter()

    if console:
        console_handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
        console_handler.setLevel(selected_level)
        console_handler.addFilter(context_filter)
        console_handler.setFormatter(selected_formatter)
        logger.addHandler(console_handler)

    if log_file is not None:
        destination = Path(log_file)
        destination.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(destination, mode="a", encoding="utf-8", delay=True)
        file_handler.setLevel(selected_level)
        file_handler.addFilter(context_filter)
        file_handler.setFormatter(selected_formatter)
        logger.addHandler(file_handler)

    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return LoggingContext(logger=logger, run_id=selected_run_id)


def get_logger(name: str | None = None) -> logging.Logger:
    """Return the VietClean logger or one of its children."""

    if name is None or name == _LOGGER_NAME:
        return logging.getLogger(_LOGGER_NAME)
    clean_name = str(name).strip().strip(".")
    return logging.getLogger(f"{_LOGGER_NAME}.{clean_name}")


def log_event(
    logger: logging.Logger,
    level: str | int,
    event: str,
    **aggregate_fields: Any,
) -> None:
    """Log a deterministic aggregate event; all field values are redacted."""

    if not isinstance(event, str) or not event.strip():
        raise ValueError("event không được để trống.")
    rendered_fields = " ".join(
        f"{key}={redact_log_text(value)}" for key, value in sorted(aggregate_fields.items())
    )
    message = f"event={redact_log_text(event)}"
    if rendered_fields:
        message += " " + rendered_fields
    logger.log(_parse_level(level), message)


__all__ = [
    "LogFormat",
    "LoggingContext",
    "SafeJsonFormatter",
    "SafeTextFormatter",
    "configure_logging",
    "get_logger",
    "get_run_id",
    "log_event",
    "new_run_id",
    "redact_log_text",
    "reset_logging",
    "set_run_id",
]
