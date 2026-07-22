"""Deterministic, privacy-preserving data-quality scoring and export.

The report contains aggregate counts only.  It never includes cell samples,
distinct values, warning text, or values from the input DataFrames.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from html import escape
import json
from numbers import Number
import os
from pathlib import Path
import tempfile
from typing import Any, cast

import pandas as pd


COMPONENT_ORDER: tuple[str, ...] = (
    "completeness",
    "validity",
    "uniqueness",
    "consistency",
    "integrity",
)

DEFAULT_QUALITY_WEIGHTS: dict[str, float] = {
    "completeness": 0.30,
    "validity": 0.25,
    "uniqueness": 0.20,
    "consistency": 0.15,
    "integrity": 0.10,
}


def _clamp_score(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 2)


def _score_from_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 100.0
    return _clamp_score(100.0 * numerator / denominator)


def _nonnegative_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _report_mapping(cleaning_report: Any) -> Mapping[str, Any]:
    if isinstance(cleaning_report, Mapping):
        return cleaning_report
    to_dict = getattr(cleaning_report, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
        if isinstance(value, Mapping):
            return value
    raise TypeError("cleaning_report must be a mapping or expose to_dict()")


def _weights_and_profile(
    profile: str | Mapping[str, Any],
) -> tuple[str, dict[str, float]]:
    """Resolve optional profile-level quality weights and normalize them."""

    profile_name = "custom"
    candidate: Any = None
    if isinstance(profile, Mapping):
        profile_name = str(profile.get("name", "custom"))
        quality = profile.get("quality", {})
        if isinstance(quality, Mapping):
            candidate = quality.get("weights")
    else:
        profile_name = str(profile)

    weights = dict(DEFAULT_QUALITY_WEIGHTS)
    if candidate is not None:
        if not isinstance(candidate, Mapping):
            raise ValueError("profile quality.weights must be a mapping")
        for component, value in candidate.items():
            if component not in COMPONENT_ORDER:
                raise ValueError(f"unknown quality component weight: {component}")
            if isinstance(value, bool) or not isinstance(value, Number):
                raise ValueError(f"quality weight for {component} must be numeric")
            numeric = float(cast(Any, value))
            if numeric < 0 or numeric != numeric or numeric in {float("inf"), float("-inf")}:
                raise ValueError(f"quality weight for {component} must be finite and non-negative")
            weights[component] = numeric

    total = sum(weights.values())
    if total <= 0:
        raise ValueError("quality weights must have a positive total")
    return profile_name, {
        component: round(weights[component] / total, 10)
        for component in COMPONENT_ORDER
    }


def _is_missing(value: Any) -> bool:
    try:
        result = pd.isna(value)
        return bool(result)
    except (TypeError, ValueError):
        return False


def _value_family(value: Any) -> str | None:
    """Return a broad type family without retaining or formatting the value."""

    if _is_missing(value):
        return None
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, Number):
        return "number"
    if isinstance(value, (datetime, date)):
        return "datetime"
    if isinstance(value, str):
        return "text"
    if isinstance(value, bytes):
        return "bytes"
    if isinstance(value, Mapping):
        return "mapping"
    if isinstance(value, Sequence):
        return "sequence"
    return "other"


def _consistency_metrics(frame: pd.DataFrame) -> tuple[int, int, int, int]:
    observed_cells = 0
    dominant_family_cells = 0
    evaluated_columns = 0
    mixed_columns = 0

    # Positional access also supports DataFrames that still have duplicate labels.
    for position in range(frame.shape[1]):
        counts: Counter[str] = Counter()
        for value in frame.iloc[:, position].array:
            family = _value_family(value)
            if family is not None:
                counts[family] += 1
        if not counts:
            continue
        evaluated_columns += 1
        column_cells = sum(counts.values())
        observed_cells += column_cells
        dominant_family_cells += max(counts.values())
        if len(counts) > 1:
            mixed_columns += 1
    return observed_cells, dominant_family_cells, evaluated_columns, mixed_columns


def _duplicate_excess(frame: pd.DataFrame) -> int:
    """Count rows beyond the first copy, without returning duplicate values."""

    if frame.empty:
        return 0
    try:
        return int(frame.duplicated(keep="first").sum())
    except (TypeError, ValueError):
        # Some object columns contain unhashable lists/dicts.  The fallback is
        # private and ephemeral; no string representation enters the report.
        normalized = frame.astype("string")
        return int(normalized.duplicated(keep="first").sum())


def _sum_invalid_counts(report: Mapping[str, Any]) -> int:
    invalid = report.get("invalid_by_column", {})
    if not isinstance(invalid, Mapping):
        return 0
    return sum(_nonnegative_int(value) for value in invalid.values())


def _sum_mapping_counts(value: Any) -> int:
    """Sum aggregate counters without copying potentially sensitive keys."""

    if not isinstance(value, Mapping):
        return 0
    return sum(_nonnegative_int(item) for item in value.values())


def _sum_nested_mapping_counts(value: Any) -> int:
    """Sum one or two levels of aggregate counters."""

    if not isinstance(value, Mapping):
        return 0
    total = 0
    for item in value.values():
        total += _sum_mapping_counts(item) if isinstance(item, Mapping) else _nonnegative_int(item)
    return total


def _sequence_count(value: Any) -> int:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return len(value)
    return _nonnegative_int(value)


def _component(
    *,
    score: float,
    weight: float,
    formula: str,
    metrics: Mapping[str, int | float],
    deduction_reason: str,
    deduction_count: int,
) -> dict[str, Any]:
    bounded = _clamp_score(score)
    return {
        "score": bounded,
        "weight": weight,
        "weighted_points": round(bounded * weight, 2),
        "formula": formula,
        "metrics": dict(metrics),
        "deduction": {
            "reason": deduction_reason,
            "count": int(max(0, deduction_count)),
            "component_points_lost": round(100.0 - bounded, 2),
        },
    }


def build_quality_report(
    before: pd.DataFrame,
    after: pd.DataFrame,
    cleaning_report: Any,
    profile: str | Mapping[str, Any] = "generic",
) -> dict[str, Any]:
    """Build a JSON-safe aggregate data-quality report.

    The overall score is the weighted arithmetic mean of five 0--100 component
    scores.  Default weights are 30% completeness, 25% validity, 20%
    uniqueness, 15% consistency, and 10% integrity.  A profile mapping may
    override ``quality.weights``; weights are then normalized to sum to 1.

    No raw value, distinct value, sample row, warning text, or PII-bearing
    invalid example is copied into the returned dictionary.
    """

    if not isinstance(before, pd.DataFrame) or not isinstance(after, pd.DataFrame):
        raise TypeError("before and after must be pandas.DataFrame objects")
    audit = _report_mapping(cleaning_report)
    profile_name, weights = _weights_and_profile(profile)

    before_rows, before_columns = int(before.shape[0]), int(before.shape[1])
    after_rows, after_columns = int(after.shape[0]), int(after.shape[1])
    before_cells = before_rows * before_columns
    after_cells = after_rows * after_columns
    before_missing = int(before.isna().to_numpy().sum())
    after_missing = int(after.isna().to_numpy().sum())
    before_observed = max(0, before_cells - before_missing)
    after_observed = max(0, after_cells - after_missing)

    completeness_score = _score_from_ratio(after_observed, after_cells)

    rejected_rows = _nonnegative_int(audit.get("rejected_rows", 0))
    validation_errors = _nonnegative_int(audit.get("validation_failed", 0))
    domain_violations = _sum_mapping_counts(audit.get("domain_rule_violations", {}))
    ambiguous_dates = _sum_mapping_counts(audit.get("ambiguous_dates_by_column", {}))
    mojibake_review = _sum_mapping_counts(audit.get("mojibake_review_by_column", {}))
    mojibake_unrepaired = _sum_mapping_counts(
        audit.get("mojibake_unrepaired_by_column", {})
    )
    invalid_detected = (
        _sum_invalid_counts(audit)
        + rejected_rows
        + validation_errors
        + domain_violations
        + ambiguous_dates
        + mojibake_review
        + mojibake_unrepaired
    )
    validity_score = (
        100.0
        if before_observed == 0 and invalid_detected == 0
        else _score_from_ratio(
            max(0, before_observed - min(before_observed, invalid_detected)),
            before_observed,
        )
        if before_observed > 0
        else 0.0
    )

    duplicate_excess = _duplicate_excess(after)
    uniqueness_score = _score_from_ratio(
        max(0, after_rows - duplicate_excess), after_rows
    )

    (
        consistency_observed,
        dominant_family_cells,
        evaluated_columns,
        mixed_columns,
    ) = _consistency_metrics(after)
    consistency_score = _score_from_ratio(
        dominant_family_cells, consistency_observed
    )

    duplicates_removed = _nonnegative_int(audit.get("duplicates_removed", 0))
    empty_rows_removed = _nonnegative_int(audit.get("empty_rows_removed", 0))
    empty_columns_removed = _sequence_count(audit.get("empty_columns_removed", ()))
    missing_rows_removed = _nonnegative_int(audit.get("missing_rows_removed", 0))
    missing_columns_removed = _sequence_count(audit.get("missing_columns_removed", ()))
    flag_columns_added = _sequence_count(audit.get("missing_flag_columns_added", ()))

    recorded_removed_rows = duplicates_removed + empty_rows_removed + missing_rows_removed
    row_gap = abs(after_rows - max(0, before_rows - recorded_removed_rows))
    row_reconciliation_score = _score_from_ratio(
        max(0, max(before_rows, after_rows, recorded_removed_rows) - row_gap),
        max(before_rows, after_rows, recorded_removed_rows),
    )

    recorded_removed_columns = empty_columns_removed + missing_columns_removed
    expected_after_columns = max(0, before_columns - recorded_removed_columns) + flag_columns_added
    column_gap = abs(after_columns - expected_after_columns)
    column_reconciliation_score = _score_from_ratio(
        max(0, max(before_columns, after_columns, recorded_removed_columns) - column_gap),
        max(before_columns, after_columns, recorded_removed_columns),
    )

    audit_dimensions = {
        "rows_before": before_rows,
        "rows_after": after_rows,
        "columns_before": before_columns,
        "columns_after": after_columns,
    }
    audit_checked = 0
    audit_mismatches = 0
    for field, actual in audit_dimensions.items():
        if field not in audit:
            continue
        reported = _optional_int(audit.get(field))
        if reported is None:
            continue
        audit_checked += 1
        audit_mismatches += int(reported != actual)
    audit_agreement_score = _score_from_ratio(
        audit_checked - audit_mismatches, audit_checked
    )
    integrity_score = _clamp_score(
        (
            row_reconciliation_score
            + column_reconciliation_score
            + audit_agreement_score
        )
        / 3.0
    )

    components = {
        "completeness": _component(
            score=completeness_score,
            weight=weights["completeness"],
            formula="100 * non_missing_cells_after / total_cells_after; empty table = 100",
            metrics={
                "total_cells_after": after_cells,
                "non_missing_cells_after": after_observed,
                "missing_cells_after": after_missing,
            },
            deduction_reason="Missing cells remaining after cleaning",
            deduction_count=after_missing,
        ),
        "validity": _component(
            score=validity_score,
            weight=weights["validity"],
            formula=(
                "100 * (observed_cells_before - capped_invalid_detections) "
                "/ observed_cells_before"
            ),
            metrics={
                "observed_cells_before": before_observed,
                "invalid_detections": invalid_detected,
                "capped_invalid_detections": min(before_observed, invalid_detected),
            },
            deduction_reason="Invalid values detected by configured or semantic rules",
            deduction_count=invalid_detected,
        ),
        "uniqueness": _component(
            score=uniqueness_score,
            weight=weights["uniqueness"],
            formula="100 * (rows_after - duplicate_excess_after) / rows_after; empty table = 100",
            metrics={
                "rows_after": after_rows,
                "duplicate_excess_after": duplicate_excess,
                "duplicates_removed": duplicates_removed,
            },
            deduction_reason="Rows remaining beyond the first identical row",
            deduction_count=duplicate_excess,
        ),
        "consistency": _component(
            score=consistency_score,
            weight=weights["consistency"],
            formula="100 * cells_in_each_column's_dominant_type_family / observed_cells_after",
            metrics={
                "observed_cells_after": consistency_observed,
                "dominant_type_family_cells": dominant_family_cells,
                "evaluated_columns": evaluated_columns,
                "mixed_type_columns": mixed_columns,
            },
            deduction_reason="Cells outside their column's dominant broad type family",
            deduction_count=max(0, consistency_observed - dominant_family_cells),
        ),
        "integrity": _component(
            score=integrity_score,
            weight=weights["integrity"],
            formula=(
                "mean(row-removal reconciliation, column-removal reconciliation, "
                "audit shape agreement)"
            ),
            metrics={
                "row_reconciliation_score": row_reconciliation_score,
                "column_reconciliation_score": column_reconciliation_score,
                "audit_shape_agreement_score": audit_agreement_score,
                "unreconciled_row_units": row_gap,
                "unreconciled_column_units": column_gap,
                "audit_dimensions_checked": audit_checked,
                "audit_dimension_mismatches": audit_mismatches,
            },
            deduction_reason="Unreconciled structural changes or audit shape mismatches",
            deduction_count=row_gap + column_gap + audit_mismatches,
        ),
    }

    overall_score = _clamp_score(
        sum(
            float(components[name]["score"]) * weights[name]
            for name in COMPONENT_ORDER
        )
    )
    warnings = audit.get("warnings", ())
    warning_count = (
        len(warnings)
        if isinstance(warnings, Sequence) and not isinstance(warnings, (str, bytes))
        else 0
    )
    encoding_repairs = _sum_mapping_counts(
        audit.get("encoding_repairs_by_column", {})
    )
    mojibake_candidates = _sum_mapping_counts(
        audit.get("mojibake_candidates_by_column", {})
    )
    outliers_detected = _sum_nested_mapping_counts(audit.get("outliers_by_column", {}))
    formula_risks = _nonnegative_int(audit.get("formula_risks_detected", 0))
    formula_sanitized = _nonnegative_int(audit.get("formula_cells_sanitized", 0))
    security_warnings = warning_count + max(0, formula_risks - formula_sanitized)

    return {
        "schema_version": "1.0",
        "profile": profile_name,
        "score": overall_score,
        "score_scale": {
            "minimum": 0,
            "maximum": 100,
            "higher_is_better": True,
        },
        "formula": {
            "method": "weighted_arithmetic_mean",
            "expression": "sum(component_score * normalized_weight)",
            "weights": weights,
            "weights_normalized": True,
        },
        "components": components,
        "summary": {
            "rows_before": before_rows,
            "rows_after": after_rows,
            "columns_before": before_columns,
            "columns_after": after_columns,
            "missing_cells_before": before_missing,
            "missing_cells_after": after_missing,
            "invalid_detections": invalid_detected,
            "validation_errors": validation_errors,
            "domain_rule_violations": domain_violations,
            "rejected_rows": rejected_rows,
            "duplicate_excess_after": duplicate_excess,
            "duplicates_removed": duplicates_removed,
            "empty_rows_removed": empty_rows_removed,
            "empty_columns_removed": empty_columns_removed,
            "missing_rows_removed": missing_rows_removed,
            "missing_columns_removed": missing_columns_removed,
            "missing_flag_columns_added": flag_columns_added,
            "encoding_repairs": encoding_repairs,
            "mojibake_candidates": mojibake_candidates,
            "ambiguous_text_values": mojibake_review + mojibake_unrepaired,
            "ambiguous_date_values": ambiguous_dates,
            "outliers_detected": outliers_detected,
            "formula_risks_detected": formula_risks,
            "formula_cells_sanitized": formula_sanitized,
            "security_warnings": security_warnings,
            "warning_count": warning_count,
        },
        "privacy": {
            "contains_raw_values": False,
            "contains_samples": False,
            "contains_warning_text": False,
            "note": (
                "Aggregate counts and scores only; no cell values or value "
                "samples are included."
            ),
        },
    }


def _format_display(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _html_report(report: Mapping[str, Any]) -> str:
    """Render only aggregate report fields; all dynamic text is escaped."""

    def safe(value: Any) -> str:
        return escape(_format_display(value), quote=True)

    profile = safe(report.get("profile", "generic"))
    score = safe(report.get("score", 0))
    formula = report.get("formula", {})
    expression = safe(
        formula.get("expression", "sum(component_score * normalized_weight)")
        if isinstance(formula, Mapping)
        else "sum(component_score * normalized_weight)"
    )

    component_rows: list[str] = []
    components = report.get("components", {})
    component_map = components if isinstance(components, Mapping) else {}
    for name in COMPONENT_ORDER:
        item = component_map.get(name, {})
        item_map = item if isinstance(item, Mapping) else {}
        deduction = item_map.get("deduction", {})
        deduction_map = deduction if isinstance(deduction, Mapping) else {}
        component_rows.append(
            "<tr>"
            f"<th scope=\"row\">{safe(name.title())}</th>"
            f"<td>{safe(item_map.get('score', 0))}</td>"
            f"<td>{safe(item_map.get('weight', 0))}</td>"
            f"<td>{safe(item_map.get('weighted_points', 0))}</td>"
            f"<td>{safe(deduction_map.get('reason', ''))}</td>"
            f"<td>{safe(deduction_map.get('count', 0))}</td>"
            "</tr>"
        )

    summary_rows: list[str] = []
    summary = report.get("summary", {})
    if isinstance(summary, Mapping):
        for key in sorted(summary, key=str):
            summary_rows.append(
                "<tr>"
                f"<th scope=\"row\">{safe(str(key).replace('_', ' ').title())}</th>"
                f"<td>{safe(summary[key])}</td>"
                "</tr>"
            )

    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VietClean Data Quality Report</title>
<style>
:root { color-scheme: light; font-family: system-ui, sans-serif; }
body { margin: 2rem auto; max-width: 72rem; padding: 0 1rem; color: #18212b; }
h1, h2 { color: #123b5d; }
.score { font-size: 2rem; font-weight: 700; color: #0b6b47; }
.meta { color: #4d5966; }
table { border-collapse: collapse; width: 100%%; margin: 1rem 0 2rem; }
th, td { border: 1px solid #ccd5dd; padding: .55rem; text-align: left; }
thead th { background: #eef4f8; }
code { background: #f1f3f5; padding: .15rem .3rem; }
.privacy { border-left: .3rem solid #0b6b47; padding: .6rem 1rem; background: #eefaf5; }
</style>
</head>
<body>
<h1>VietClean Data Quality Report</h1>
<p class="score">Data Quality Score: %s/100</p>
<p class="meta">Profile: %s</p>
<p>Overall formula: <code>%s</code>. Scores and weights are shown below.</p>
<h2>Components</h2>
<table>
<thead><tr><th>Component</th><th>Score</th><th>Weight</th>
<th>Weighted points</th><th>Deduction reason</th><th>Count</th></tr></thead>
<tbody>%s</tbody>
</table>
<h2>Aggregate summary</h2>
<table><tbody>%s</tbody></table>
<p class="privacy"><strong>Privacy:</strong> Aggregate counts only.
No raw values, samples, or warning text are included.</p>
</body>
</html>
""" % (score, profile, expression, "".join(component_rows), "".join(summary_rows))


def _atomic_write(path: Path, content: str) -> None:
    destination = path.expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def write_quality_report(
    report: Mapping[str, Any],
    json_path: str | os.PathLike[str],
    html_path: str | os.PathLike[str] | None = None,
    *,
    overwrite: bool = False,
) -> None:
    """Atomically write deterministic JSON and optional self-contained HTML."""

    if not isinstance(report, Mapping):
        raise TypeError("report must be a mapping")
    if not isinstance(overwrite, bool):
        raise TypeError("overwrite phải là true hoặc false.")
    json_destination = Path(json_path)
    html_destination = Path(html_path) if html_path is not None else None
    if html_destination is not None:
        json_key = os.path.normcase(os.path.abspath(json_destination))
        html_key = os.path.normcase(os.path.abspath(html_destination))
        if json_key == html_key:
            raise ValueError("json_path and html_path must be different")
    for destination in (json_destination, html_destination):
        if destination is not None and destination.exists() and not overwrite:
            raise FileExistsError(
                f"Quality report already exists: {destination}. Pass overwrite=True explicitly."
            )

    try:
        json_content = json.dumps(
            dict(report),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ) + "\n"
    except (TypeError, ValueError) as exc:
        raise ValueError("report must contain JSON-safe finite values") from exc

    _atomic_write(json_destination, json_content)
    if html_destination is not None:
        _atomic_write(html_destination, _html_report(report))


__all__ = [
    "COMPONENT_ORDER",
    "DEFAULT_QUALITY_WEIGHTS",
    "build_quality_report",
    "write_quality_report",
]
