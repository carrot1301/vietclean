"""Non-mutating, aggregate-only schema validation."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd

from .config import ConfigError, load_config
from .models import ValidationIssue, ValidationResult
from .pipeline import DataCleaner
from .profiles import normalize_column_name


_CLEANING_CONFIG_KEYS = {
    "version",
    "strict",
    "profile",
    "preset",
    "locale",
    "auto_types",
    "text",
    "missing",
    "type_conversion",
    "column_names",
    "drop",
    "duplicates",
    "columns",
    "domain_rules",
    "quality",
    "outliers",
}


def _column_lookup(columns: pd.Index) -> dict[str, object]:
    lookup: dict[str, object] = {}
    for column in columns:
        key = normalize_column_name(column)
        if key and key not in lookup:
            lookup[key] = column
    return lookup


def validate_dataframe(
    frame: pd.DataFrame,
    schema: str | Path | Mapping[str, Any],
    *,
    profile: str | None = None,
) -> ValidationResult:
    """Validate *frame* without mutating it or returning raw invalid values.

    A schema is a normal VietClean TOML/JSON configuration with optional
    ``required_columns`` and ``allow_extra_columns`` keys. Column rules reuse
    the same ``type``, ``required``, ``min``, ``max``, ``regex`` and ``allowed``
    contract as cleaning.
    """

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame phải là pandas.DataFrame.")
    loaded = load_config(schema)
    if not isinstance(loaded, Mapping):
        raise ConfigError("Schema phải là object/table.")
    selected = deepcopy(dict(loaded))
    raw_rules = selected.get("columns", {})
    if not isinstance(raw_rules, Mapping):
        raise ConfigError("schema.columns phải là object/table.")

    requested_required = selected.get("required_columns", [])
    if isinstance(requested_required, str):
        required_columns = [requested_required]
    elif isinstance(requested_required, (list, tuple)) and all(
        isinstance(item, str) for item in requested_required
    ):
        required_columns = list(requested_required)
    else:
        raise ConfigError("required_columns phải là tên cột hoặc danh sách tên cột.")
    for name, rule in raw_rules.items():
        if isinstance(rule, Mapping) and rule.get("required") and str(name) not in required_columns:
            required_columns.append(str(name))

    issues: list[ValidationIssue] = []
    lookup = _column_lookup(frame.columns)
    missing_required: set[str] = set()
    for requested in required_columns:
        if normalize_column_name(requested) not in lookup:
            missing_required.add(requested)
            issues.append(
                ValidationIssue(
                    code="VC-VALIDATE-002",
                    column=requested,
                    rule="required_column",
                    count=1,
                    message=f"Thiếu cột bắt buộc: {requested}.",
                )
            )

    allow_extra = selected.get("allow_extra_columns", True)
    if not isinstance(allow_extra, bool):
        raise ConfigError("allow_extra_columns phải là true hoặc false.")
    if not allow_extra:
        expected = {normalize_column_name(name) for name in raw_rules}
        extras = [str(column) for column in frame.columns if normalize_column_name(column) not in expected]
        for column in extras:
            issues.append(
                ValidationIssue(
                    code="VC-VALIDATE-003",
                    column=column,
                    rule="allow_extra_columns",
                    count=1,
                    message=f"Cột không có trong schema: {column}.",
                )
            )

    cleaning_config = {
        key: deepcopy(value) for key, value in selected.items() if key in _CLEANING_CONFIG_KEYS
    }
    cleaning_config["strict"] = False
    cleaning_config["auto_types"] = False
    cleaning_config.setdefault("duplicates", {})["enabled"] = False
    cleaning_config.setdefault("drop", {}).update(
        {"empty_rows": False, "empty_columns": False}
    )
    # Missing columns are already represented by aggregate issues; omit their
    # rule so the normal cleaner can validate every present column safely.
    cleaning_config["columns"] = {
        name: deepcopy(rule)
        for name, rule in raw_rules.items()
        if str(name) not in missing_required
    }
    cleaner = DataCleaner(profile=profile, config=cleaning_config)
    cleaning = cleaner.clean(frame, inplace=False)

    cleaned_missing = {
        normalize_column_name(column): (str(column), int(count))
        for column, count in cleaning.report.missing_after.items()
    }
    for requested in required_columns:
        if requested in missing_required:
            continue
        match = cleaned_missing.get(normalize_column_name(requested))
        if match is not None and match[1] > 0:
            issues.append(
                ValidationIssue(
                    code="VC-VALIDATE-006",
                    column=match[0],
                    rule="required",
                    count=match[1],
                    message=f"Cột bắt buộc {match[0]} còn thiếu {match[1]} giá trị.",
                )
            )

    for column, count in sorted(cleaning.report.invalid_by_column.items()):
        issues.append(
            ValidationIssue(
                code="VC-VALIDATE-004",
                column=column,
                rule="column_rule",
                count=int(count),
                message=f"Cột {column} có {count} giá trị không hợp lệ.",
            )
        )
    for rule, count in sorted(cleaning.report.domain_rule_violations.items()):
        issues.append(
            ValidationIssue(
                code="VC-VALIDATE-005",
                rule=rule,
                count=int(count),
                message=f"Rule nghiệp vụ {rule} có {count} vi phạm.",
            )
        )

    checks_failed = len(issues)
    checks_defined = len(required_columns) + sum(
        1
        for rule in raw_rules.values()
        if isinstance(rule, Mapping) and any(
            key in rule for key in ("type", "required", "min", "max", "regex", "allowed")
        )
    )
    checks_defined += len(cleaning.report.domain_rule_violations)
    result = ValidationResult(
        valid=checks_failed == 0,
        rows=int(len(frame)),
        columns=int(len(frame.columns)),
        checks_passed=max(0, checks_defined - checks_failed),
        checks_failed=checks_failed,
        issues=issues,
        warnings=list(cleaning.report.warnings),
    )
    return result


__all__ = ["validate_dataframe"]
