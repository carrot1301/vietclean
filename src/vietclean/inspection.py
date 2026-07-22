"""Read-only data quality inspection helpers."""

from __future__ import annotations

import unicodedata
from numbers import Number
from typing import Any, cast

import pandas as pd
from pandas.api.types import (
    is_bool_dtype,
    is_datetime64_any_dtype,
    is_numeric_dtype,
    is_object_dtype,
    is_string_dtype,
)

from .profiles import resolve_semantic_type
from .security.formulas import is_formula_risk
from .security.pii import infer_pii_type


_MOJIBAKE_MARKERS = ("Ã", "Â", "Ä", "áº", "á»", "ï¿½", "�")


def inspect_dataframe(
    frame: pd.DataFrame,
    *,
    profile: str = "generic",
    include_samples: bool = False,
    sample_size: int = 3,
    max_unique_values: int = 100_000,
) -> dict[str, Any]:
    """Return a JSON-serialisable snapshot without changing the DataFrame."""

    if sample_size < 0 or sample_size > 100:
        raise ValueError("sample_size phải nằm trong [0, 100].")
    if max_unique_values <= 0:
        raise ValueError("max_unique_values phải lớn hơn 0.")

    columns: list[dict[str, Any]] = []
    for column in frame.columns:
        series = frame[column]
        missing = int(series.isna().sum())
        unique, unique_truncated, unique_approximate = _bounded_unique_count(
            series, max_unique_values
        )
        details: dict[str, Any] = {
            "name": str(column),
            "dtype": str(series.dtype),
            "semantic_type": resolve_semantic_type(str(column), profile),
            "missing": missing,
            "missing_percent": round((missing / len(frame) * 100) if len(frame) else 0.0, 2),
            "unique": unique,
            "unique_truncated": unique_truncated,
            "unique_approximate": unique_approximate,
            "possible_pii": infer_pii_type(column),
        }
        non_missing = series.dropna()
        details["high_cardinality"] = bool(
            len(non_missing) >= 100
            and (unique_truncated or details["unique"] / max(1, len(non_missing)) >= 0.90)
        )
        if is_numeric_dtype(series.dtype) and not is_bool_dtype(series.dtype):
            details["numeric"] = {
                "min": _json_scalar(non_missing.min()) if not non_missing.empty else None,
                "max": _json_scalar(non_missing.max()) if not non_missing.empty else None,
                "median": _json_scalar(non_missing.median()) if not non_missing.empty else None,
            }
            if not non_missing.empty:
                first_quartile = non_missing.quantile(0.25)
                third_quartile = non_missing.quantile(0.75)
                iqr = third_quartile - first_quartile
                lower = first_quartile - 1.5 * iqr
                upper = third_quartile + 1.5 * iqr
                details["numeric"]["iqr_outliers"] = int(
                    ((non_missing < lower) | (non_missing > upper)).sum()
                )
        elif is_datetime64_any_dtype(series.dtype):
            details["date"] = {
                "min": _json_scalar(non_missing.min()) if not non_missing.empty else None,
                "max": _json_scalar(non_missing.max()) if not non_missing.empty else None,
            }
        if is_object_dtype(series.dtype) or is_string_dtype(series.dtype):
            strings = series.dropna().map(lambda value: value if isinstance(value, str) else "")
            details["leading_or_trailing_space"] = int(
                strings.map(lambda value: value != value.strip()).sum()
            )
            details["contains_line_break"] = int(strings.str.contains(r"[\r\n]", regex=True).sum())
            details["possible_mojibake"] = int(
                strings.map(lambda value: any(marker in value for marker in _MOJIBAKE_MARKERS)).sum()
            )
            details["repeated_whitespace"] = int(
                strings.str.contains(r"[^\S\r\n]{2,}", regex=True).sum()
            )
            details["replacement_character"] = int(strings.str.contains("�", regex=False).sum())
            details["unexpected_control_character"] = int(
                strings.map(
                    lambda value: any(
                        unicodedata.category(char) == "Cc" and char not in "\t\r\n"
                        for char in value
                    )
                ).sum()
            )
            details["formula_injection_risk"] = int(strings.map(is_formula_risk).sum())
            lengths = strings.map(len)
            details["text_length"] = {
                "min": int(lengths.min()) if not lengths.empty else None,
                "max": int(lengths.max()) if not lengths.empty else None,
            }
        if include_samples:
            # Samples are opt-in because business data often contains PII.
            details["samples"] = [
                _json_scalar(value) for value in _bounded_distinct_samples(series, sample_size)
            ]
        columns.append(details)

    duplicate_rows, duplicate_rows_approximate = _duplicate_row_count(frame)
    return {
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "duplicate_rows": duplicate_rows,
        "duplicate_rows_approximate": duplicate_rows_approximate,
        "completely_empty_rows": int(frame.isna().all(axis=1).sum()),
        "completely_empty_columns": [
            str(column) for column in frame.columns if frame[column].isna().all()
        ],
        "column_details": columns,
    }


def _duplicate_row_count(frame: pd.DataFrame) -> tuple[int, bool]:
    try:
        return int(frame.duplicated().sum()), False
    except (TypeError, ValueError):
        mapper = getattr(frame, "map", None)
        if callable(mapper):
            frozen = mapper(_freeze_for_duplicate)
        else:  # pandas 1.5 compatibility; DataFrame.map arrived later.
            frozen = getattr(frame, "applymap")(_freeze_for_duplicate)
        return int(frozen.duplicated().sum()), True


def _freeze_for_duplicate(value: Any) -> Any:
    if isinstance(value, dict):
        return (
            "mapping",
            tuple(
                sorted(
                    (
                        (_freeze_for_duplicate(key), _freeze_for_duplicate(item))
                        for key, item in value.items()
                    ),
                    key=lambda pair: str(pair[0]),
                )
            ),
        )
    if isinstance(value, (list, tuple)):
        return ("sequence", tuple(_freeze_for_duplicate(item) for item in value))
    if isinstance(value, (set, frozenset)):
        return ("set", frozenset(_freeze_for_duplicate(item) for item in value))
    try:
        hash(value)
    except TypeError:
        return ("unhashable", type(value).__name__)
    return value


def _bounded_unique_count(series: pd.Series, limit: int) -> tuple[int, bool, bool]:
    """Count distinct scalar values without an unbounded cardinality set."""

    seen: set[object] = set()
    approximate = False
    for value in series.array:
        try:
            if bool(pd.isna(value)):
                continue
        except (TypeError, ValueError):
            pass
        try:
            marker: object = (type(value), value)
            if marker in seen:
                continue
            if len(seen) >= limit:
                return len(seen), True, approximate
            seen.add(marker)
        except TypeError:
            # Lists/dicts are unusual tabular cells. Count them conservatively
            # without retaining their potentially sensitive representation.
            approximate = True
            if len(seen) >= limit:
                return len(seen), True, approximate
            marker = ("unhashable", len(seen))
            seen.add(marker)
    return len(seen), False, approximate


def _bounded_distinct_samples(series: pd.Series, limit: int) -> list[Any]:
    output: list[Any] = []
    seen: set[object] = set()
    if limit == 0:
        return output
    for value in series.array:
        try:
            if bool(pd.isna(value)):
                continue
        except (TypeError, ValueError):
            pass
        try:
            marker: object = (type(value), value)
            if marker in seen:
                continue
            seen.add(marker)
        except TypeError:
            # Unhashable samples are rare; do not build a representation that
            # could retain more sensitive data than the explicit sample itself.
            marker = ("unhashable", len(output))
            seen.add(marker)
        output.append(value)
        if len(output) >= limit:
            break
    return output


def _json_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    if isinstance(value, Number):
        numeric = float(cast(Any, value))
        return int(numeric) if numeric.is_integer() else numeric
    return str(value)
