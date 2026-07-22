import io
import json
import logging
from pathlib import Path

import pytest

from vietclean.logging_utils import (
    configure_logging,
    get_logger,
    log_event,
    redact_log_text,
    reset_logging,
    set_run_id,
)


@pytest.fixture(autouse=True)
def _clean_vietclean_handlers():
    reset_logging()
    yield
    reset_logging()


def test_redaction_masks_credentials_pii_tokens_and_log_injection() -> None:
    source = (
        "postgresql://alice:secret@db.internal:5432/sales?token=abc#frag "
        "password=hunter2 client_secret=oauth-secret Authorization=Bearer bearer-secret "
        "email=alice@example.com phone=0901234567\nforged"
    )

    safe = redact_log_text(source)

    for secret in (
        "alice:secret",
        "token=abc",
        "hunter2",
        "oauth-secret",
        "bearer-secret",
        "alice@example.com",
        "0901234567",
    ):
        assert secret not in safe
    assert "postgresql://***@db.internal:5432/sales" in safe
    assert "password=***" in safe
    assert "client_secret=***" in safe
    assert "Authorization=*** ***" in safe
    assert "a***@example.com" in safe
    assert "***4567" in safe
    assert r"\nforged" in safe
    assert "\nforged" not in safe.replace(r"\nforged", "")


def test_text_logging_has_run_id_defaults_to_info_and_redacts_debug(tmp_path: Path) -> None:
    destination = tmp_path / "run.log"
    context = configure_logging(
        log_file=destination,
        run_id="run-20260722",
        console=False,
    )

    context.logger.debug("email=user@example.com")
    context.logger.info("rows=%d uri=%s", 12, "mysql://u:p@db.local/data?key=x")
    reset_logging()

    content = destination.read_text(encoding="utf-8")
    assert "DEBUG" not in content
    assert "level=INFO" in content
    assert "run_id=run-20260722" in content
    assert "mysql://***@db.local/data" in content
    assert "u:p" not in content and "?key=x" not in content


def test_json_logging_uses_allowlisted_schema_and_redacts_exception() -> None:
    stream = io.StringIO()
    configure_logging(
        level="DEBUG",
        log_format="json",
        run_id="fixed_run",
        stream=stream,
    )
    logger = get_logger("worker")

    try:
        raise RuntimeError("api_key=top-secret user@example.com")
    except RuntimeError:
        logger.exception("Xử lý lỗi cho 0901234567")

    payload = json.loads(stream.getvalue())
    assert set(payload) == {"timestamp", "level", "logger", "run_id", "message", "exception"}
    assert payload["level"] == "ERROR"
    assert payload["logger"] == "vietclean.worker"
    assert payload["run_id"] == "fixed_run"
    rendered = json.dumps(payload, ensure_ascii=False)
    assert "top-secret" not in rendered
    assert "user@example.com" not in rendered
    assert "0901234567" not in rendered


def test_logger_name_cannot_inject_a_line_or_leak_pii() -> None:
    stream = io.StringIO()
    configure_logging(log_format="json", run_id="fixed_run", stream=stream)

    get_logger("worker\nuser@example.com").info("aggregate only")

    payload = json.loads(stream.getvalue())
    assert "\n" not in payload["logger"]
    assert "user@example.com" not in payload["logger"]
    assert r"\n" in payload["logger"]


def test_logging_boundary_levels_null_handler_url_port_and_append(tmp_path: Path) -> None:
    assert "secret" not in redact_log_text("custom:///secret").casefold()
    assert redact_log_text("https://example.invalid:bad/path") == (
        "https://example.invalid/path"
    )

    destination = tmp_path / "append.log"
    destination.write_text("existing\n", encoding="utf-8")
    context = configure_logging(
        level=logging.CRITICAL,
        log_file=destination,
        console=False,
        run_id="append-run",
    )
    context.logger.critical("aggregate")
    reset_logging()
    assert destination.read_text(encoding="utf-8").startswith("existing\n")

    context = configure_logging(level=logging.ERROR, console=False)
    assert isinstance(context.logger.handlers[0], logging.NullHandler)
    assert get_logger().name == "vietclean"
    assert get_logger("vietclean").name == "vietclean"

    with pytest.raises(ValueError, match="log level"):
        configure_logging(level=True)
    with pytest.raises(ValueError, match="dạng số"):
        configure_logging(level=25)


def test_log_event_is_deterministic_and_root_logger_is_not_modified() -> None:
    stream = io.StringIO()
    root_handlers = tuple(logging.getLogger().handlers)
    context = configure_logging(level=logging.WARNING, run_id="job_1", stream=stream)

    log_event(context.logger, "WARNING", "validation_summary", z=2, a=1)

    assert "event=validation_summary a=1 z=2" in stream.getvalue()
    assert tuple(logging.getLogger().handlers) == root_handlers


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        (lambda: set_run_id("bad id"), "run_id"),
        (lambda: configure_logging(level="TRACE"), "log level"),
        (lambda: configure_logging(log_format="xml"), "log_format"),  # type: ignore[arg-type]
        (lambda: configure_logging(console=1), "console"),  # type: ignore[arg-type]
    ],
)
def test_logging_configuration_rejects_unsafe_or_ambiguous_values(operation, message) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        operation()
