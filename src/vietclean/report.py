"""Structured cleaning reports with no dependency beyond the standard library."""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version
import os
import platform
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _package_version(distribution: str) -> str | None:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return None


@dataclass(slots=True)
class CleaningReport:
    """Machine-readable audit trail for one cleaning run."""

    profile: str = "generic"
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "running"
    framework_version: str = "0.1.0"
    python_version: str = field(default_factory=platform.python_version)
    operating_system: str = field(default_factory=platform.system)
    pandas_version: str | None = field(default_factory=lambda: _package_version("pandas"))
    openpyxl_version: str | None = field(default_factory=lambda: _package_version("openpyxl"))
    started_at: str = field(default_factory=_utc_now)
    finished_at: str | None = None
    rows_before: int = 0
    rows_after: int = 0
    columns_before: int = 0
    columns_after: int = 0
    cells_changed: int = 0
    changed_by_column: dict[str, int] = field(default_factory=dict)
    changed_by_rule: dict[str, int] = field(default_factory=dict)
    missing_before: dict[str, int] = field(default_factory=dict)
    missing_after: dict[str, int] = field(default_factory=dict)
    semantic_types: dict[str, str] = field(default_factory=dict)
    invalid_by_column: dict[str, int] = field(default_factory=dict)
    encoding_repairs_by_column: dict[str, int] = field(default_factory=dict)
    mojibake_candidates_by_column: dict[str, int] = field(default_factory=dict)
    mojibake_review_by_column: dict[str, int] = field(default_factory=dict)
    mojibake_unrepaired_by_column: dict[str, int] = field(default_factory=dict)
    ambiguous_dates_by_column: dict[str, int] = field(default_factory=dict)
    missing_filled_by_column: dict[str, int] = field(default_factory=dict)
    missing_fill_strategy_by_column: dict[str, str] = field(default_factory=dict)
    missing_rows_removed: int = 0
    missing_columns_removed: list[str] = field(default_factory=list)
    missing_flag_columns_added: list[str] = field(default_factory=list)
    duplicates_detected: int = 0
    duplicates_detected_by_subset: int = 0
    duplicates_removed: int = 0
    empty_rows_removed: int = 0
    empty_columns_removed: list[str] = field(default_factory=list)
    renamed_columns: dict[str, str] = field(default_factory=dict)
    formula_mode: str = "sanitize"
    formula_risks_detected: int = 0
    formula_cells_sanitized: int = 0
    formula_risks_by_column: dict[str, int] = field(default_factory=dict)
    rejected_rows: int = 0
    rejected_by_reason: dict[str, int] = field(default_factory=dict)
    validation_passed: int = 0
    validation_failed: int = 0
    domain_rule_violations: dict[str, int] = field(default_factory=dict)
    outliers_by_column: dict[str, dict[str, int]] = field(default_factory=dict)
    quality_score: float | None = None
    source_name: str | None = None
    source_size_bytes: int | None = None
    source_sheet_count: int | None = None
    source_table_count: int | None = None
    streaming_mode: bool = False
    chunks_processed: int = 0
    sheet_reports: dict[str, dict[str, Any]] = field(default_factory=dict)
    loader_encoding: str | None = None
    loader_delimiter: str | None = None
    input_sha256: str | None = None
    config_sha256: str | None = None
    output_sha256: str | None = None
    artifact_sha256: dict[str, str] = field(default_factory=dict)
    steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None

    def finish(self, *, status: str = "success") -> "CleaningReport":
        """Mark the report as complete and return it for fluent use."""

        if status not in {"success", "failed", "cancelled"}:
            raise ValueError("status phải là success, failed hoặc cancelled.")
        self.status = status
        self.finished_at = _utc_now()
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(
        self,
        path: str | Path | None = None,
        *,
        indent: int = 2,
        overwrite: bool = False,
    ) -> str:
        """Serialize as UTF-8 JSON and optionally persist it."""

        if not isinstance(overwrite, bool):
            raise TypeError("overwrite phải là true hoặc false.")
        content = json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
        if path is not None:
            destination = Path(path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and not overwrite:
                raise FileExistsError(
                    f"Report đã tồn tại: {destination}. Dùng overwrite=True để ghi đè."
                )
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(content + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_name, destination)
            except BaseException:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
                raise
        return content


@dataclass(slots=True)
class CleaningResult:
    """The cleaned DataFrame together with its audit report."""

    data: "pd.DataFrame"
    report: CleaningReport
