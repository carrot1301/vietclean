"""Small, pipe-friendly DataFrame transformations.

Every function returns a deep copy and never mutates the caller's DataFrame.
They are useful when a full :class:`vietclean.pipeline.DataCleaner` run would
be too broad for a notebook or an existing pandas pipeline.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal

import pandas as pd
from pandas.api.types import is_object_dtype, is_string_dtype

from .profiles import normalize_column_name as _profile_column_name
from .text import (
    DEFAULT_MISSING_TOKENS,
    WhitespaceMode,
    analyze_mojibake,
    is_missing,
    normalize_unicode as _normalize_unicode_scalar,
    normalize_whitespace as _normalize_whitespace_scalar,
    remove_invisible_chars,
)


def _selected_columns(frame: pd.DataFrame, columns: Iterable[Any] | None) -> list[Any]:
    selected = list(frame.columns if columns is None else columns)
    missing = [column for column in selected if column not in frame.columns]
    if missing:
        raise KeyError(f"columns not found: {missing}")
    return selected


def clean_names(
    frame: pd.DataFrame,
    *,
    style: Literal["snake_case", "lower_snake_case", "upper_snake_case", "preserve"] =
    "lower_snake_case",
) -> pd.DataFrame:
    """Return a copy with clean, deterministic, unique column names."""

    return normalize_column_names(frame, style=style)


def normalize_unicode(
    frame: pd.DataFrame,
    columns: Iterable[Any] | None = None,
    *,
    form: Literal["NFC", "NFKC"] = "NFC",
) -> pd.DataFrame:
    """Return a copy with selected string cells normalized to NFC or NFKC."""

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas.DataFrame")
    _normalize_unicode_scalar("", form=form)
    output = frame.copy(deep=True)
    for column in _selected_columns(output, columns):
        output[column] = output[column].map(
            lambda value: _normalize_unicode_scalar(value, form=form)
            if isinstance(value, str)
            else value
        )
    return output


def repair_vietnamese_text(
    frame: pd.DataFrame,
    columns: Iterable[Any] | None = None,
    *,
    confidence_threshold: float = 0.90,
) -> pd.DataFrame:
    """Return a copy with only high-confidence Vietnamese mojibake repaired."""

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas.DataFrame")
    analyze_mojibake("", confidence_threshold=confidence_threshold)
    output = frame.copy(deep=True)
    for column in _selected_columns(output, columns):
        output[column] = output[column].map(
            lambda value: analyze_mojibake(
                value,
                confidence_threshold=confidence_threshold,
            ).value
            if isinstance(value, str)
            else value
        )
    return output


def normalize_whitespace(
    frame: pd.DataFrame,
    columns: Iterable[Any] | None = None,
    *,
    mode: WhitespaceMode = "normalize_spaces",
) -> pd.DataFrame:
    """Return a copy with a configured whitespace mode applied to text cells."""

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas.DataFrame")
    _normalize_whitespace_scalar("", mode=mode)
    output = frame.copy(deep=True)
    for column in _selected_columns(output, columns):
        output[column] = output[column].map(
            lambda value: _normalize_whitespace_scalar(value, mode=mode)
            if isinstance(value, str)
            else value
        )
    return output


def standardize_missing(
    frame: pd.DataFrame,
    columns: Iterable[Any] | None = None,
    *,
    config: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Return a copy with missing tokens standardized from a small config map.

    Supported keys are ``tokens``, ``replacement``, ``case_sensitive``,
    ``accent_sensitive`` and ``strip_before_match``.  This intentionally does
    not impute or delete data; those policies belong to ``DataCleaner``.
    """

    options = dict(config or {})
    allowed = {
        "tokens",
        "replacement",
        "case_sensitive",
        "accent_sensitive",
        "strip_before_match",
    }
    unknown = set(options) - allowed
    if unknown:
        raise ValueError(f"unsupported missing config keys: {sorted(unknown)}")
    for key in ("case_sensitive", "accent_sensitive", "strip_before_match"):
        if key in options and not isinstance(options[key], bool):
            raise TypeError(f"missing config {key} must be a boolean")
    configured_tokens = options.get("tokens", DEFAULT_MISSING_TOKENS)
    if isinstance(configured_tokens, str):
        configured_tokens = (configured_tokens,)
    return replace_missing(
        frame,
        columns=columns,
        tokens=configured_tokens,
        replacement=options.get("replacement", pd.NA),
        case_sensitive=options.get("case_sensitive", False),
        accent_sensitive=options.get("accent_sensitive", False),
        strip_before_match=options.get("strip_before_match", True),
    )


def coerce_types(
    frame: pd.DataFrame,
    *,
    schema: Mapping[str, Any],
    locale: str = "vi_VN",
    invalid: Literal["keep", "missing", "raise"] = "keep",
) -> pd.DataFrame:
    """Return a copy with schema-declared semantic types coerced.

    ``schema`` maps column names either to a semantic type string or to a full
    column rule accepted by :class:`vietclean.pipeline.DataCleaner`.
    """

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas.DataFrame")
    if not isinstance(schema, Mapping):
        raise TypeError("schema must be a mapping")
    column_rules: dict[str, dict[str, Any]] = {}
    for column, raw_rule in schema.items():
        if isinstance(raw_rule, str):
            rule = {"type": raw_rule}
        elif isinstance(raw_rule, Mapping):
            rule = dict(raw_rule)
        else:
            raise TypeError(f"schema rule for {column!r} must be a string or mapping")
        rule.setdefault("invalid", invalid)
        column_rules[str(column)] = rule

    # Local import avoids a module cycle: pipeline itself uses ``deduplicate``.
    from .pipeline import DataCleaner

    cleaner = DataCleaner(
        config={
            "locale": locale,
            "auto_types": False,
            "text": {
                "whitespace_mode": "preserve",
                "repair_mojibake": False,
                "remove_invisible": False,
            },
            "column_names": {
                "style": "preserve",
                "strip": False,
                "line_breaks": "preserve",
                "deduplicate": False,
            },
            "columns": column_rules,
        }
    )
    return cleaner.clean(frame).data


def flag_duplicates(
    frame: pd.DataFrame,
    *,
    subset: Iterable[Any] | None = None,
    flag_column: str = "is_duplicate",
    keep: Literal["first", "last"] | bool = False,
) -> pd.DataFrame:
    """Return a copy with an exact-duplicate boolean flag; remove no rows."""

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas.DataFrame")
    if not isinstance(flag_column, str) or not flag_column:
        raise ValueError("flag_column must be a non-empty string")
    if flag_column in frame.columns:
        raise ValueError(f"flag column already exists: {flag_column}")
    if keep not in {"first", "last", False}:
        raise ValueError("keep must be first, last, or False")
    selected = None if subset is None else list(subset)
    if selected is not None:
        _selected_columns(frame, selected)
    output = frame.copy(deep=True)
    output[flag_column] = output.duplicated(subset=selected, keep=keep)
    return output


def validate_schema(
    frame: pd.DataFrame,
    *,
    schema: Mapping[str, Any],
    locale: str = "vi_VN",
) -> pd.DataFrame:
    """Validate and return an unchanged copy, raising on schema violations."""

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas.DataFrame")
    if not isinstance(schema, Mapping):
        raise TypeError("schema must be a mapping")
    raw_columns = schema.get("columns", schema)
    if not isinstance(raw_columns, Mapping):
        raise TypeError("schema.columns must be a mapping")

    from .exceptions import SchemaValidationError
    from .validation import validate_dataframe

    normalized_rules: dict[str, Any] = {}
    for column, raw_rule in raw_columns.items():
        if isinstance(raw_rule, str):
            normalized_rules[str(column)] = {"type": raw_rule}
        elif isinstance(raw_rule, Mapping):
            normalized = dict(raw_rule)
            if normalized.pop("nullable", True) is False:
                normalized["required"] = True
            normalized_rules[str(column)] = normalized
        else:
            raise TypeError(f"schema rule for {column!r} must be a string or mapping")
    schema_config = {
        "locale": locale,
        "columns": normalized_rules,
        "required_columns": schema.get("required_columns", []),
        "allow_extra_columns": schema.get("allow_extra_columns", True),
    }
    result = validate_dataframe(frame, schema_config)
    if not result.valid:
        summary = ", ".join(
            f"{issue.rule}:{issue.count}" for issue in result.issues[:10]
        )
        raise SchemaValidationError(
            f"Schema có {result.checks_failed} kiểm tra không đạt ({summary})."
        )
    return frame.copy(deep=True)


def normalize_text(
    frame: pd.DataFrame,
    *,
    columns: Iterable[Any] | None = None,
    unicode_form: Literal["NFC", "NFKC"] = "NFC",
    whitespace_mode: WhitespaceMode = "normalize_spaces",
    repair_mojibake: bool = True,
    mojibake_confidence_threshold: float = 0.90,
    remove_invisible: bool = True,
) -> pd.DataFrame:
    """Return a copy with selected text columns safely normalized."""

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas.DataFrame")
    output = frame.copy(deep=True)
    for column in _selected_columns(output, columns):
        series = output[column]
        if not (is_object_dtype(series.dtype) or is_string_dtype(series.dtype)):
            continue

        def clean(value: object) -> object:
            if not isinstance(value, str):
                return value
            text = _normalize_unicode_scalar(value, form=unicode_form)
            if remove_invisible:
                text = remove_invisible_chars(text)
            if repair_mojibake:
                text = analyze_mojibake(
                    text,
                    confidence_threshold=mojibake_confidence_threshold,
                ).value
            return _normalize_whitespace_scalar(text, mode=whitespace_mode)

        output[column] = series.map(clean)
    return output


def replace_missing(
    frame: pd.DataFrame,
    *,
    columns: Iterable[Any] | None = None,
    tokens: Iterable[str] = DEFAULT_MISSING_TOKENS,
    replacement: object = pd.NA,
    case_sensitive: bool = False,
    accent_sensitive: bool = False,
    strip_before_match: bool = True,
) -> pd.DataFrame:
    """Return a copy with configured missing tokens replaced."""

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas.DataFrame")
    output = frame.copy(deep=True)
    frozen_tokens = (tokens,) if isinstance(tokens, str) else tuple(tokens)
    for column in _selected_columns(output, columns):
        output[column] = output[column].map(
            lambda value: replacement
            if is_missing(
                value,
                frozen_tokens,
                case_sensitive=case_sensitive,
                accent_sensitive=accent_sensitive,
                strip_before_match=strip_before_match,
            )
            else value
        )
    return output


def normalize_column_names(
    frame: pd.DataFrame,
    *,
    style: Literal["snake_case", "lower_snake_case", "upper_snake_case", "preserve"] =
    "lower_snake_case",
) -> pd.DataFrame:
    """Return a copy whose column names use a deterministic, unique style."""

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas.DataFrame")
    if style not in {"snake_case", "lower_snake_case", "upper_snake_case", "preserve"}:
        raise ValueError("unsupported column-name style")
    output = frame.copy(deep=True)
    names: list[str] = []
    used: set[str] = set()
    for position, column in enumerate(output.columns, start=1):
        original = _normalize_whitespace_scalar(str(column), mode="single_line")
        if style == "preserve":
            base = original
        else:
            base = _profile_column_name(original)
            if style == "upper_snake_case":
                base = base.upper()
        if not base:
            base = f"column_{position}"
        name = base
        suffix = 2
        while name in used:
            name = f"{base}_{suffix}"
            suffix += 1
        used.add(name)
        names.append(name)
    output.columns = names
    return output


def deduplicate(
    frame: pd.DataFrame,
    *,
    subset: Iterable[Any] | None = None,
    keep: Literal["first", "last", "most_complete"] | bool = "first",
) -> pd.DataFrame:
    """Return a copy with exact duplicates removed by an explicit policy."""

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas.DataFrame")
    selected = None if subset is None else list(subset)
    if selected is not None:
        _selected_columns(frame, selected)
    if keep not in {"first", "last", "most_complete", False}:
        raise ValueError("keep must be first, last, most_complete, or False")
    if keep != "most_complete":
        return frame.drop_duplicates(subset=selected, keep=keep).copy(deep=True)

    work = frame.copy(deep=True)
    original_columns = list(work.columns)
    score_column = "__vietclean_score"
    position_column = "__vietclean_position"
    while score_column in work.columns:
        score_column += "_"
    while position_column in work.columns or position_column == score_column:
        position_column += "_"
    score = work.notna().sum(axis=1)
    position = pd.Series(range(len(work)), index=work.index)
    ranked = work.copy(deep=True)
    ranked[score_column] = score.to_numpy()
    ranked[position_column] = position.to_numpy()
    ranked.sort_values(
        [score_column, position_column],
        ascending=[False, True],
        kind="stable",
        inplace=True,
    )
    chosen = ranked.drop_duplicates(
        subset=selected if selected is not None else original_columns,
        keep="first",
    ).copy(deep=True)
    chosen.sort_values(position_column, kind="stable", inplace=True)
    return chosen.drop(columns=[score_column, position_column]).copy(deep=True)


__all__ = [
    "clean_names",
    "coerce_types",
    "deduplicate",
    "flag_duplicates",
    "normalize_column_names",
    "normalize_text",
    "normalize_unicode",
    "normalize_whitespace",
    "repair_vietnamese_text",
    "replace_missing",
    "standardize_missing",
    "validate_schema",
]
