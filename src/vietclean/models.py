"""Small JSON-safe models shared by the public API and command line."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Aggregate schema violation that never contains a raw cell value."""

    code: str
    message: str
    column: str | None = None
    rule: str | None = None
    count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ValidationResult:
    """Result of validating one in-memory table against a local schema."""

    valid: bool
    rows: int
    columns: int
    checks_passed: int = 0
    checks_failed: int = 0
    issues: list[ValidationIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "rows": self.rows,
            "columns": self.columns,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "issues": [issue.to_dict() for issue in self.issues],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class FileCleaningResult:
    """Paths and aggregate metadata produced by :func:`clean_file`."""

    output_path: Path
    audit_path: Path
    quality_json_path: Path
    quality_html_path: Path | None
    rejects_path: Path
    column_mapping_path: Path
    run_summary_path: Path
    rows_before: int
    rows_after: int
    quality_score: float
    run_id: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key, value in list(result.items()):
            if isinstance(value, Path):
                result[key] = str(value)
        return result


__all__ = ["FileCleaningResult", "ValidationIssue", "ValidationResult"]
