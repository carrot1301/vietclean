"""Spreadsheet formula-injection detection and neutralisation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Sequence

import pandas as pd
from pandas.api.types import is_object_dtype, is_string_dtype

from ..text import parse_vietnamese_number


FormulaMode = Literal["sanitize", "report_only", "allow"]


@dataclass(slots=True)
class FormulaProtectionResult:
    """Protected data and aggregate-only audit information."""

    data: pd.DataFrame
    mode: FormulaMode
    risks_detected: int = 0
    cells_sanitized: int = 0
    by_column: dict[str, int] = field(default_factory=dict)


def is_formula_risk(value: object) -> bool:
    """Return whether a string may be evaluated by spreadsheet software.

    Negative numeric strings are not treated as injection payloads. Leading
    ``+`` is always protected because spreadsheet applications can interpret
    it as a formula prefix; this includes phone numbers, whose displayed value
    remains unchanged after apostrophe-prefix sanitisation.
    """

    if not isinstance(value, str) or not value:
        return False
    if value.startswith("'"):
        return False
    if value[0] in {"\t", "\r", "\n", "\v", "\f"}:
        return True
    candidate = value.lstrip()
    if not candidate or candidate.startswith("'"):
        return False
    first = candidate[0]
    if first in {"\t", "\r", "\n", "\v", "\f"}:
        return True
    if first in {"=", "@"}:
        return True
    if first == "+":
        return True
    if first == "-":
        return parse_vietnamese_number(candidate) is None
    return False


def protect_spreadsheet_formulas(
    frame: pd.DataFrame,
    *,
    mode: FormulaMode = "sanitize",
    columns: Sequence[str] | None = None,
    copy: bool = True,
) -> FormulaProtectionResult:
    """Detect or sanitize formula-like strings without mutating by default."""

    if mode not in {"sanitize", "report_only", "allow"}:
        raise ValueError("formula mode phải là sanitize, report_only hoặc allow.")
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame phải là pandas.DataFrame.")
    if not isinstance(copy, bool):
        raise TypeError("copy phải là true hoặc false.")
    data = frame.copy(deep=True) if copy else frame
    selected = list(data.columns) if columns is None else list(columns)
    missing = [column for column in selected if column not in data.columns]
    if missing:
        raise KeyError(f"Cột formula protection không tồn tại: {missing}")

    by_column: dict[str, int] = {}
    for column in selected:
        series = data[column]
        categorical = isinstance(series.dtype, pd.CategoricalDtype)
        if not (is_object_dtype(series.dtype) or is_string_dtype(series.dtype) or categorical):
            continue
        if categorical:
            series = series.astype(object)
            data[column] = series
        risk = series.map(is_formula_risk)
        count = int(risk.sum())
        if not count:
            continue
        by_column[str(column)] = count
        if mode == "sanitize":
            data.loc[risk, column] = series[risk].map(lambda value: "'" + value)

    detected = sum(by_column.values())
    return FormulaProtectionResult(
        data=data,
        mode=mode,
        risks_detected=detected,
        cells_sanitized=detected if mode == "sanitize" else 0,
        by_column=by_column,
    )
