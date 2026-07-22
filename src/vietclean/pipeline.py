"""Configurable, offline data-cleaning pipeline."""

from __future__ import annotations

import re
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, cast, overload

import pandas as pd
from pandas.api.types import is_object_dtype, is_string_dtype

from .config import BASE_CONFIG, ConfigError, deep_merge, load_config, validate_config
from .domain import validate_domain_rules
from .exceptions import SchemaValidationError
from .profiles import get_profile, resolve_semantic_type
from .report import CleaningReport, CleaningResult
from .transforms import deduplicate as deduplicate_frame
from .text import (
    LineBreakMode,
    analyze_mojibake,
    is_missing,
    normalize_email,
    normalize_phone,
    normalize_unicode,
    normalize_whitespace,
    parse_vietnamese_currency,
    parse_vietnamese_number,
    remove_invisible_chars,
    repair_mojibake,
)


class CleaningError(SchemaValidationError):
    """Raised when a configured cleaning or validation rule cannot be fulfilled."""


@dataclass(slots=True)
class _Conversion:
    values: pd.Series
    invalid: pd.Series
    attempted: int
    succeeded: int
    review_count: int = 0

    @property
    def success_rate(self) -> float:
        return self.succeeded / self.attempted if self.attempted else 1.0


def _plain_name(
    value: Any, *, line_breaks: LineBreakMode = "space", trim: bool = True
) -> str:
    text = normalize_unicode(str(value))
    text = remove_invisible_chars(text)
    text = repair_mojibake(text)
    return normalize_whitespace(text, line_breaks=line_breaks, trim=trim)


def _key(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value).casefold())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", "", text)


def _snake_case(value: str) -> str:
    text = unicodedata.normalize("NFD", value)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D")
    return re.sub(r"_+", "_", re.sub(r"[^0-9A-Za-z]+", "_", text)).strip("_")


def _scalar_is_na(value: Any) -> bool:
    try:
        result = pd.isna(value)
        return bool(result)
    except (TypeError, ValueError):
        return False


def _same_value(left: Any, right: Any) -> bool:
    if _scalar_is_na(left) and _scalar_is_na(right):
        return True
    if _scalar_is_na(left) or _scalar_is_na(right):
        return False
    try:
        equal = left == right
        return bool(equal)
    except (TypeError, ValueError):
        return False


def _count_changes(before: pd.Series, after: pd.Series) -> int:
    """Count value changes positionally while both frames still have equal rows.

    Comparing by label breaks for the common pandas case of duplicate indexes:
    ``Series.at[label]`` then returns a Series rather than a scalar.
    """

    if len(before) != len(after):
        raise ValueError("change tracking requires equally sized Series")
    return sum(
        not _same_value(left, right)
        for left, right in zip(before.array, after.array)
    )


def _profile_defaults(profile: Mapping[str, Any]) -> Mapping[str, Any]:
    """Accept both the public profile shape and earlier simple profile mappings."""

    for key in ("defaults", "config", "settings"):
        value = profile.get(key)
        if isinstance(value, Mapping):
            return value
    known = set(BASE_CONFIG)
    return {key: value for key, value in profile.items() if key in known}


_MAX_USER_REGEX_LENGTH = 256
_QUANTIFIED_GROUP_RE = re.compile(r"\)(?:[+*]|\{\d+(?:,\d*)?\})")
_BACKREFERENCE_RE = re.compile(r"\\[1-9]|\(\?P=")


def _compile_user_regex(expression: str) -> re.Pattern[str]:
    """Compile a deliberately restricted validation regex.

    Python's standard regex engine has no execution timeout. Rejecting long
    expressions, backreferences, lookarounds and quantified groups keeps local
    config from introducing common catastrophic-backtracking forms such as
    ``(a+)+$``. Simple anchored business validators remain supported.
    """

    if len(expression) > _MAX_USER_REGEX_LENGTH:
        raise ConfigError(
            f"regex vượt quá {_MAX_USER_REGEX_LENGTH} ký tự và bị từ chối vì an toàn."
        )
    if "\x00" in expression:
        raise ConfigError("regex chứa ký tự NUL và bị từ chối.")
    if _BACKREFERENCE_RE.search(expression):
        raise ConfigError("regex dùng backreference và bị từ chối vì nguy cơ ReDoS.")
    if any(token in expression for token in ("(?=", "(?!", "(?<=", "(?<!", "(?(")):
        raise ConfigError("regex dùng lookaround/conditional và bị từ chối vì an toàn.")
    if _QUANTIFIED_GROUP_RE.search(expression):
        raise ConfigError("regex có group lặp và bị từ chối vì nguy cơ ReDoS.")
    # Two unbounded wildcards commonly turn full-string validation quadratic.
    if expression.count(".*") + expression.count(".+") > 1:
        raise ConfigError("regex có nhiều wildcard không giới hạn và bị từ chối vì an toàn.")
    return re.compile(expression)


class DataCleaner:
    """Clean a DataFrame using a built-in industry profile plus JSON overrides.

    The cleaner is deliberately conservative: automatic semantic types only run
    when a column name matches a known alias, and inferred type conversions are
    skipped when too many non-missing values would fail.
    """

    def __init__(
        self,
        *,
        profile: str | None = None,
        config: str | Mapping[str, Any] | None = None,
    ) -> None:
        user_config = load_config(config)
        configured_profile = user_config.pop("profile", None)
        if configured_profile is None:
            configured_profile = user_config.pop("preset", None)
        selected = (
            profile
            if profile is not None
            else str(configured_profile) if configured_profile is not None else "generic"
        )
        # Locale alone supplies deterministic separator/date defaults.  An
        # explicit type_conversion value always wins, and unknown locales are
        # left untouched rather than guessed.
        locale = user_config.get("locale")
        if isinstance(locale, str):
            locale_defaults = {
                "vi_vn": (",", ".", True),
                "en_us": (".", ",", False),
                "en_gb": (".", ",", True),
            }.get(locale.replace("-", "_").casefold())
            if locale_defaults is not None:
                raw_conversion = user_config.get("type_conversion", {})
                conversion_override = (
                    deepcopy(dict(raw_conversion))
                    if isinstance(raw_conversion, Mapping)
                    else raw_conversion
                )
                if isinstance(conversion_override, dict):
                    decimal, thousands, day_first = locale_defaults
                    conversion_override.setdefault("decimal_separator", decimal)
                    conversion_override.setdefault("thousands_separator", thousands)
                    conversion_override.setdefault("day_first", day_first)
                    user_config["type_conversion"] = conversion_override
        try:
            profile_data = get_profile(selected)
        except (KeyError, ValueError) as exc:
            raise ConfigError(str(exc)) from exc
        merged = deep_merge(BASE_CONFIG, _profile_defaults(profile_data))
        self.config = deep_merge(merged, user_config)
        validate_config(self.config)
        self.profile = str(profile_data.get("name", selected))

    def clean(self, frame: pd.DataFrame, *, inplace: bool = False) -> CleaningResult:
        """Return cleaned data and a complete audit report."""

        if not isinstance(frame, pd.DataFrame):
            raise TypeError("DataCleaner.clean chỉ nhận pandas.DataFrame.")
        if not isinstance(inplace, bool):
            raise TypeError("inplace phải là true hoặc false.")

        data = frame if inplace else frame.copy(deep=True)
        report = CleaningReport(
            profile=self.profile,
            rows_before=len(data),
            columns_before=len(data.columns),
        )

        new_columns, renamed = self._clean_column_names(list(data.columns))
        data.columns = new_columns
        report.renamed_columns = renamed
        baseline = data.copy(deep=True)
        report.missing_before = {str(c): int(baseline[c].isna().sum()) for c in baseline}

        report.steps.extend(["clean_column_names", "normalize_text_and_missing"])
        self._clean_text_columns(data, report)

        explicit_rules = self.config.get("columns", {})
        for column in list(data.columns):
            rule, explicit = self._rule_for_column(column, explicit_rules)
            semantic = rule.get("type")
            if not semantic and self.config.get("auto_types", True):
                semantic = resolve_semantic_type(str(column), self.profile)
            if semantic:
                semantic = str(semantic).lower()
                report.semantic_types[str(column)] = semantic
                self._apply_semantic_type(data, column, semantic, rule, explicit, report)
            self._apply_value_rules(data, column, rule, report, semantic=semantic)
        report.steps.extend(["semantic_type_conversion", "column_value_rules"])

        # Track transformations before rows/columns are intentionally removed.
        # At this point baseline and data have the same row order, including for
        # DataFrames whose index labels are duplicated.
        for column in data.columns:
            if column not in baseline.columns:
                continue
            changed = _count_changes(baseline[column], data[column])
            if changed:
                report.changed_by_column[str(column)] = changed
        report.cells_changed = sum(report.changed_by_column.values())

        self._apply_structural_missing(data, report)
        self._audit_duplicates(data, report)
        self._drop_empty(data, report)
        data = self._drop_duplicates(data, report)
        self._audit_outliers(data, report)
        self._apply_domain_rules(data, report)
        self._add_required_warnings(data, report)
        report.steps.extend(
            [
                "drop_configured_empty_rows_columns",
                "duplicate_policy",
                "outlier_detection",
                "domain_validation",
            ]
        )

        report.rows_after = len(data)
        report.columns_after = len(data.columns)
        report.missing_after = {str(c): int(data[c].isna().sum()) for c in data}
        report.finish()
        return CleaningResult(data=data, report=report)

    def _clean_column_names(self, columns: list[Any]) -> tuple[list[str], dict[str, str]]:
        options = self.config.get("column_names", {})
        output: list[str] = []
        renamed: dict[str, str] = {}
        used: set[str] = set()
        original_counts: dict[str, int] = {}
        for position, original in enumerate(columns, start=1):
            name = _plain_name(
                original,
                line_breaks=cast(
                    LineBreakMode, str(options.get("line_breaks", "space"))
                ),
                trim=bool(options.get("strip", True)),
            )
            if options.get("lowercase"):
                name = name.casefold()
            if options.get("snake_case"):
                name = _snake_case(name)
            style = options.get("style", "preserve")
            if style != "preserve":
                name = _snake_case(name)
                if style == "lower_snake_case":
                    name = name.casefold()
                elif style == "upper_snake_case":
                    name = name.upper()
            if not name:
                name = f"column_{position}"
            if options.get("deduplicate", True):
                base = name
                suffix = 2
                while name in used:
                    name = f"{base}_{suffix}"
                    suffix += 1
            used.add(name)
            output.append(name)
            original_label = str(original)
            original_counts[original_label] = original_counts.get(original_label, 0) + 1
            if str(original) != name:
                label = original_label
                if original_counts[original_label] > 1 or label in renamed:
                    label = f"{label} [{position}]"
                renamed[label] = name
        if len(used) != len(output):
            raise ConfigError(
                "Tên cột vẫn bị trùng; hãy bật column_names.deduplicate để xử lý an toàn."
            )
        return output, renamed

    def _clean_text_columns(self, data: pd.DataFrame, report: CleaningReport) -> None:
        options = self.config.get("text", {})
        missing = self.config.get("missing", {})
        default_tokens = missing.get("tokens", [])
        case_sensitive = bool(missing.get("case_sensitive", False))
        accent_sensitive = bool(missing.get("accent_sensitive", False))
        strip_before_match = bool(missing.get("strip_before_match", True))
        rules = self.config.get("columns", {})

        for column in data.columns:
            series = data[column]
            if is_object_dtype(series.dtype) or is_string_dtype(series.dtype):
                repaired_count = 0
                candidate_count = 0
                review_count = 0
                unrepaired_count = 0
                rule, _ = self._rule_for_column(column, rules)
                tokens = rule.get("missing_tokens", default_tokens)
                whitespace_mode = rule.get(
                    "whitespace_mode",
                    rule.get(
                        "line_break_mode",
                        options.get(
                            "whitespace_mode",
                            options.get(
                                "line_break_mode", options.get("line_breaks", "keep")
                            ),
                        ),
                    ),
                )

                def tracked_clean(value: Any) -> Any:
                    nonlocal candidate_count, repaired_count, review_count, unrepaired_count
                    if not isinstance(value, str):
                        return value
                    cleaned = normalize_unicode(
                        value, form=options.get("unicode_form", "NFC")
                    )
                    if options.get("remove_invisible", True):
                        cleaned = remove_invisible_chars(
                            cleaned,
                            remove_joiners=bool(options.get("remove_joiners", False)),
                        )
                    if options.get(
                        "repair_vietnamese_mojibake",
                        options.get("repair_mojibake", True),
                    ):
                        decision = analyze_mojibake(
                            cleaned,
                            confidence_threshold=float(
                                options.get("mojibake_confidence_threshold", 0.90)
                            ),
                        )
                        if decision.candidates:
                            candidate_count += 1
                        if decision.changed:
                            repaired_count += 1
                        if decision.needs_review:
                            review_count += 1
                        if decision.unrepaired:
                            unrepaired_count += 1
                        cleaned = decision.value
                    if is_missing(
                        cleaned,
                        tokens=tokens,
                        case_sensitive=case_sensitive,
                        accent_sensitive=accent_sensitive,
                        strip_before_match=strip_before_match,
                    ):
                        return pd.NA
                    cleaned = normalize_whitespace(
                        cleaned,
                        line_breaks=whitespace_mode,
                        trim=options.get("trim", True),
                        tabs_to_spaces=bool(options.get("tabs_to_spaces", True)),
                        collapse_spaces=bool(
                            options.get(
                                "normalize_spaces",
                                options.get("collapse_whitespace", True),
                            )
                        ),
                        normalize_non_breaking_space=bool(
                            options.get("normalize_non_breaking_space", True)
                        ),
                    )
                    return cleaned

                data[column] = series.map(tracked_clean)
                if repaired_count:
                    report.encoding_repairs_by_column[str(column)] = repaired_count
                if candidate_count:
                    report.mojibake_candidates_by_column[str(column)] = candidate_count
                if review_count:
                    report.mojibake_review_by_column[str(column)] = review_count
                if unrepaired_count:
                    report.mojibake_unrepaired_by_column[str(column)] = unrepaired_count

    def _rule_for_column(
        self, column: Any, rules: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        if column in rules and isinstance(rules[column], Mapping):
            return deepcopy(dict(rules[column])), True
        wanted = _key(column)
        for name, rule in rules.items():
            if _key(name) == wanted and isinstance(rule, Mapping):
                return deepcopy(dict(rule)), True
        return {}, False

    def _apply_semantic_type(
        self,
        data: pd.DataFrame,
        column: Any,
        semantic: str,
        rule: Mapping[str, Any],
        explicit: bool,
        report: CleaningReport,
    ) -> None:
        series = data[column]
        if semantic in {"text", "identifier", "category", "address"}:
            return
        if semantic == "email":
            conversion = self._map_conversion(series, normalize_email)
        elif semantic == "phone":
            default_country = str(rule.get("default_country", "VN"))
            conversion = self._map_conversion(
                series, lambda value: normalize_phone(value, default_country=default_country)
            )
        elif semantic in {"number", "percentage", "currency", "integer"}:
            conversion_options = self.config.get("type_conversion", {})
            decimal_separator = str(
                rule.get(
                    "decimal_separator", conversion_options.get("decimal_separator", ",")
                )
            )
            thousands_separator = str(
                rule.get(
                    "thousands_separator",
                    conversion_options.get("thousands_separator", "."),
                )
            )
            decimal_comma = bool(rule.get("decimal_comma", decimal_separator == ","))
            if "decimal_comma" in rule and "decimal_separator" not in rule:
                decimal_separator = "," if decimal_comma else "."
                if "thousands_separator" not in rule:
                    thousands_separator = "." if decimal_comma else ","
            if semantic == "currency":
                expected_currency = str(
                    rule.get("currency", conversion_options.get("currency", "VND"))
                )

                def parser(value: Any) -> Any:
                    return parse_vietnamese_currency(
                        value,
                        decimal_comma=decimal_comma,
                        expected_currency=expected_currency,
                        decimal_separator=decimal_separator,
                        thousands_separator=thousands_separator,
                    )
            else:
                percent_as_fraction = bool(
                    rule.get("percent_as_fraction", semantic == "percentage")
                )
                bare_percentage = str(rule.get("bare_percentage", "reject"))

                def parser(value: Any) -> Any:
                    if semantic == "percentage":
                        has_percent = isinstance(value, str) and value.strip().endswith("%")
                        if not has_percent and bare_percentage == "reject":
                            return None
                    parsed = parse_vietnamese_number(
                        value,
                        decimal_comma=decimal_comma,
                        percent_as_fraction=percent_as_fraction
                        if semantic == "percentage"
                        else False,
                        decimal_separator=decimal_separator,
                        thousands_separator=thousands_separator,
                    )
                    if (
                        semantic == "percentage"
                        and parsed is not None
                        and not has_percent
                        and bare_percentage == "percent"
                    ):
                        return parsed / 100
                    return parsed
            conversion = self._map_conversion(series, parser)
            if semantic == "integer":
                non_integer = conversion.values.map(
                    lambda value: False
                    if _scalar_is_na(value)
                    else value != value.to_integral_value()
                )
                conversion.invalid = conversion.invalid | non_integer
                conversion.values = conversion.values.mask(non_integer)
                conversion.succeeded = int((~conversion.invalid & series.notna()).sum())
        elif semantic in {"date", "datetime"}:
            conversion = self._date_conversion(
                series,
                date_only=semantic == "date",
                rule=rule,
            )
        elif semantic == "boolean":
            conversion = self._boolean_conversion(series, rule)
        else:
            report.warnings.append(f"Bỏ qua kiểu không được hỗ trợ '{semantic}' ở cột {column}.")
            return

        minimum = float(self.config.get("type_conversion", {}).get("minimum_success_rate", 0.8))
        if not explicit and conversion.success_rate < minimum:
            report.warnings.append(
                f"Không ép kiểu cột {column} thành {semantic}: chỉ nhận diện được "
                f"{conversion.success_rate:.0%}."
            )
            return

        invalid_count = int(conversion.invalid.sum())
        if conversion.review_count:
            report.ambiguous_dates_by_column[str(column)] = conversion.review_count
        if invalid_count:
            report.invalid_by_column[str(column)] = (
                report.invalid_by_column.get(str(column), 0) + invalid_count
            )
        policy = str(rule.get("invalid", self.config["type_conversion"].get("invalid", "keep")))
        if policy == "raise" and invalid_count:
            raise CleaningError(
                f"Cột {column} có {invalid_count} giá trị {semantic} không hợp lệ."
            )
        if policy == "keep":
            # ``Series.where`` may coerce a parseable-but-rejected date string
            # back into Timestamp to satisfy the datetime dtype.  Build an
            # object Series positionally so an invalid value is truly kept,
            # including when index labels are duplicated.
            if invalid_count:
                data[column] = pd.Series(
                    [
                        original if bool(is_invalid) else converted
                        for original, converted, is_invalid in zip(
                            series.array,
                            conversion.values.array,
                            conversion.invalid.array,
                        )
                    ],
                    index=series.index,
                    name=series.name,
                    dtype="object",
                )
            else:
                data[column] = conversion.values
        elif policy in {"missing", "raise"}:
            # A raise policy reaches this branch only when every attempted
            # value was valid, so the successful conversion must still apply.
            data[column] = conversion.values
        else:
            raise ConfigError(f"invalid='{policy}' không hợp lệ ở cột {column}.")

    @staticmethod
    def _map_conversion(series: pd.Series, parser: Callable[[Any], Any]) -> _Conversion:
        attempted_mask = series.notna()

        def safe_parse(value: Any) -> Any:
            if _scalar_is_na(value):
                return None
            try:
                return parser(value)
            except (TypeError, ValueError, OverflowError):
                return None

        values = series.map(safe_parse)
        invalid = attempted_mask & values.isna()
        return _Conversion(
            values=values,
            invalid=invalid,
            attempted=int(attempted_mask.sum()),
            succeeded=int((attempted_mask & ~invalid).sum()),
        )

    def _date_conversion(
        self,
        series: pd.Series,
        *,
        date_only: bool,
        rule: Mapping[str, Any],
    ) -> _Conversion:
        attempted = series.notna()
        conversion_options = self.config.get("type_conversion", {})
        configured_day_first = rule.get(
            "day_first", conversion_options.get("day_first", True)
        )
        locale = self.config.get("locale")
        if configured_day_first is None:
            locale_key = str(locale).replace("-", "_").casefold() if locale else ""
            if locale_key.startswith("vi_") or locale_key in {"vi", "en_gb"}:
                day_first: bool | None = True
            elif locale_key.startswith("en_us"):
                day_first = False
            else:
                day_first = None
        else:
            day_first = bool(configured_day_first)
        timezone_policy = str(conversion_options.get("timezone_policy", "preserve"))
        min_year = conversion_options.get("min_year")
        max_year = conversion_options.get("max_year")
        excel_serial = bool(
            rule.get("excel_serial", conversion_options.get("excel_serial", True))
        )
        date_format = rule.get("format")
        if date_format is not None and not isinstance(date_format, str):
            raise ConfigError("format ngày phải là chuỗi strftime.")
        ambiguous_count = 0

        def parse(value: Any) -> Any:
            nonlocal ambiguous_count
            if _scalar_is_na(value):
                return pd.NaT
            if (
                excel_serial
                and not isinstance(value, (bool, str))
                and isinstance(value, (int, float))
            ):
                numeric = float(value)
                if not 1 <= numeric <= 2_958_465:
                    return pd.NaT
                try:
                    parsed = pd.to_datetime(
                        numeric,
                        unit="D",
                        origin="1899-12-30",
                        errors="raise",
                    )
                except (TypeError, ValueError, OverflowError):
                    return pd.NaT
                if not isinstance(parsed, pd.Timestamp):
                    return pd.NaT
                if min_year is not None and parsed.year < int(min_year):
                    return pd.NaT
                if max_year is not None and parsed.year > int(max_year):
                    return pd.NaT
                return parsed.normalize() if date_only else parsed
            scalar_day_first = day_first
            scalar_year_first = False
            if isinstance(value, str) and date_format is None:
                ambiguous = re.fullmatch(
                    r"\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})(?:\s+.*)?\s*",
                    value,
                )
                if (
                    ambiguous
                    and int(ambiguous.group(1)) <= 12
                    and int(ambiguous.group(2)) <= 12
                    and day_first is None
                ):
                    ambiguous_count += 1
                    return pd.NaT
            if isinstance(value, str) and re.match(
                r"^\s*\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:\D|$)", value
            ):
                # dayfirst=True can reinterpret an otherwise unambiguous ISO
                # date such as 2026-01-02 as 1 February on some pandas versions.
                scalar_day_first = False
                scalar_year_first = True
            try:
                parsed = pd.to_datetime(
                    value,
                    errors="raise",
                    dayfirst=bool(scalar_day_first),
                    yearfirst=scalar_year_first,
                    format=date_format,
                )
            except (TypeError, ValueError, OverflowError):
                return pd.NaT
            # A DataFrame cell should yield one Timestamp. Reject list-like
            # objects instead of placing a DatetimeIndex inside a cell.
            if not isinstance(parsed, pd.Timestamp):
                return pd.NaT
            if min_year is not None and parsed.year < int(min_year):
                return pd.NaT
            if max_year is not None and parsed.year > int(max_year):
                return pd.NaT
            if parsed.tzinfo is not None:
                if timezone_policy == "naive":
                    parsed = parsed.tz_localize(None)
                elif timezone_policy == "utc":
                    parsed = parsed.tz_convert("UTC")
                elif timezone_policy == "naive_utc":
                    parsed = parsed.tz_convert("UTC").tz_localize(None)
            elif timezone_policy == "utc":
                parsed = parsed.tz_localize("UTC")
            return parsed.normalize() if date_only else parsed

        # Parse scalars independently. Pandas 2.x otherwise infers one strict
        # format for the whole Series, while format="mixed" is absent in 1.5.
        converted = series.map(parse)
        invalid = attempted & converted.isna()
        return _Conversion(
            values=converted,
            invalid=invalid,
            attempted=int(attempted.sum()),
            succeeded=int((attempted & ~invalid).sum()),
            review_count=ambiguous_count,
        )

    def _boolean_conversion(
        self, series: pd.Series, rule: Mapping[str, Any]
    ) -> _Conversion:
        conversion_options = self.config.get("type_conversion", {})
        truthy = {
            normalize_whitespace(value).casefold()
            for value in rule.get(
                "true_values", conversion_options.get("boolean_true", [])
            )
        }
        falsy = {
            normalize_whitespace(value).casefold()
            for value in rule.get(
                "false_values", conversion_options.get("boolean_false", [])
            )
        }

        def parse(value: Any) -> Any:
            if isinstance(value, bool):
                return value
            normalized = normalize_whitespace(str(value)).casefold()
            if normalized in truthy:
                return True
            if normalized in falsy:
                return False
            return None

        return self._map_conversion(series, parse)

    def _apply_value_rules(
        self,
        data: pd.DataFrame,
        column: Any,
        rule: Mapping[str, Any],
        report: CleaningReport,
        *,
        semantic: Any = None,
    ) -> None:
        policy = str(rule.get("invalid", "keep"))
        if policy not in {"keep", "missing", "raise"}:
            raise ConfigError(f"invalid='{policy}' không hợp lệ ở cột {column}.")
        series = data[column]
        replacements = rule.get("map", rule.get("replace"))
        if isinstance(replacements, Mapping):
            direct = dict(replacements)
            folded = {str(key).casefold(): value for key, value in direct.items()}

            def replace(value: Any) -> Any:
                if _scalar_is_na(value):
                    return value
                try:
                    if value in direct:
                        return direct[value]
                except TypeError:
                    pass
                return folded.get(str(value).casefold(), value)

            series = series.map(replace)

        case = rule.get("case")
        if case in {"lower", "upper", "title", "casefold"}:
            transform = {
                "lower": str.lower,
                "upper": str.upper,
                "title": str.title,
                "casefold": str.casefold,
            }[case]
            series = series.map(lambda value: transform(value) if isinstance(value, str) else value)

        invalid = pd.Series(False, index=series.index)
        if "min" in rule:
            numeric = pd.to_numeric(series, errors="coerce")
            invalid |= series.notna() & numeric.lt(rule["min"])
        if "max" in rule:
            numeric = pd.to_numeric(series, errors="coerce")
            invalid |= series.notna() & numeric.gt(rule["max"])
        if "regex" in rule:
            try:
                pattern = _compile_user_regex(str(rule["regex"]))
            except re.error as exc:
                raise ConfigError(f"regex không hợp lệ ở cột {column}: {exc}") from exc
            invalid |= series.notna() & ~series.astype("string").str.fullmatch(pattern, na=False)
        if "allowed" in rule:
            raw_allowed = rule["allowed"]
            if isinstance(raw_allowed, (str, bytes)) or not isinstance(
                raw_allowed, (list, tuple, set, frozenset)
            ):
                raise ConfigError(f"allowed phải là một danh sách ở cột {column}.")
            try:
                allowed = set(raw_allowed)
            except TypeError as exc:
                raise ConfigError(f"allowed chỉ được chứa giá trị scalar ở cột {column}.") from exc
            invalid |= series.notna() & ~series.isin(allowed)
        if invalid.any():
            count = int(invalid.sum())
            report.invalid_by_column[str(column)] = (
                report.invalid_by_column.get(str(column), 0) + count
            )
            if policy == "missing":
                series = series.mask(invalid)
            elif policy == "raise":
                raise CleaningError(f"Cột {column} có {count} giá trị vi phạm điều kiện.")

        missing_strategy = rule.get("missing_strategy")
        if missing_strategy is None and "fill" not in rule and not rule.get("fill_strategy"):
            missing_strategy = self.config.get("missing", {}).get(
                "default_strategy", "keep"
            )
        supported_missing = {
            None,
            "keep",
            "drop_row",
            "drop_column",
            "fill_constant",
            "fill_zero",
            "fill_mean",
            "fill_median",
            "fill_mode",
            "forward_fill",
            "backward_fill",
            "group_median",
            "group_mode",
            "flag_only",
        }
        if missing_strategy not in supported_missing:
            raise ConfigError(
                f"missing_strategy='{missing_strategy}' không hợp lệ ở cột {column}."
            )
        if missing_strategy == "fill_mean" and str(semantic).casefold() == "identifier":
            raise ConfigError(f"Không được dùng fill_mean cho mã định danh {column}.")

        before_fill = int(series.isna().sum())
        if missing_strategy == "flag_only":
            flag_name = str(rule.get("flag_column", f"{column}_was_missing"))
            if flag_name in data.columns:
                raise ConfigError(f"Cột cờ missing đã tồn tại: {flag_name}")
            data[flag_name] = series.isna()
            report.missing_flag_columns_added.append(flag_name)
        elif missing_strategy == "fill_zero":
            series = series.fillna(0)
        elif missing_strategy == "fill_constant":
            if "fill" not in rule:
                raise ConfigError(f"fill_constant cần key fill ở cột {column}.")
            series = series.fillna(rule["fill"])
        elif missing_strategy in {"fill_mean", "fill_median", "fill_mode"}:
            strategy = str(missing_strategy).removeprefix("fill_")
            series = self._fill_series(series, strategy, column)
        elif missing_strategy == "forward_fill":
            series = series.ffill()
        elif missing_strategy == "backward_fill":
            series = series.bfill()
        elif missing_strategy in {"group_median", "group_mode"}:
            group_by = rule.get("group_by")
            groups = [group_by] if isinstance(group_by, str) else list(group_by or [])
            missing_groups = [name for name in groups if name not in data.columns]
            if not groups or missing_groups:
                raise ConfigError(
                    f"{missing_strategy} cần group_by hợp lệ ở cột {column}: {missing_groups}"
                )
            strategy = str(missing_strategy).removeprefix("group_")

            def group_fill(values: pd.Series) -> pd.Series:
                return self._fill_series(values, strategy, column)

            temporary = data.assign(__vietclean_value=series)
            series = temporary.groupby(groups, dropna=False)["__vietclean_value"].transform(
                group_fill
            )
        elif "fill" in rule and missing_strategy is None:
            series = series.fillna(rule["fill"])
        elif rule.get("fill_strategy") and missing_strategy is None:
            series = self._fill_series(series, str(rule["fill_strategy"]), column)

        filled = before_fill - int(series.isna().sum())
        if filled:
            report.missing_filled_by_column[str(column)] = filled
            applied_strategy = missing_strategy
            if applied_strategy is None:
                applied_strategy = (
                    str(rule["fill_strategy"])
                    if rule.get("fill_strategy")
                    else "fill_constant"
                )
            report.missing_fill_strategy_by_column[str(column)] = str(applied_strategy)

        data[column] = series

    @staticmethod
    def _fill_series(series: pd.Series, strategy: str, column: Any) -> pd.Series:
        non_missing = series.dropna()
        if non_missing.empty:
            return series
        if strategy == "mode":
            modes = non_missing.mode()
            return series.fillna(modes.iloc[0]) if not modes.empty else series
        if strategy in {"median", "mean"}:
            numeric = pd.to_numeric(non_missing, errors="coerce").dropna()
            if numeric.empty:
                return series
            value = numeric.median() if strategy == "median" else numeric.mean()
            return series.fillna(value)
        raise ConfigError(f"fill strategy='{strategy}' không hợp lệ ở cột {column}.")

    def _apply_structural_missing(
        self, data: pd.DataFrame, report: CleaningReport
    ) -> None:
        rules = self.config.get("columns", {})
        default_strategy = self.config.get("missing", {}).get(
            "default_strategy", "keep"
        )
        drop_mask = pd.Series(False, index=data.index)
        drop_columns: list[Any] = []
        for column in list(data.columns):
            rule, _ = self._rule_for_column(column, rules)
            strategy = rule.get("missing_strategy", default_strategy)
            if strategy == "drop_row":
                drop_mask |= data[column].isna()
            elif strategy == "drop_column" and data[column].isna().any():
                drop_columns.append(column)
        if drop_mask.any():
            report.missing_rows_removed = int(drop_mask.sum())
            mask = drop_mask.to_numpy(dtype=bool)
            kept_index = data.index[~mask]
            data.index = pd.RangeIndex(len(data))
            data.drop(index=data.index[mask], inplace=True)
            data.index = kept_index
        if drop_columns:
            data.drop(columns=drop_columns, inplace=True)
            report.missing_columns_removed = [str(column) for column in drop_columns]

    def _add_required_warnings(
        self, data: pd.DataFrame, report: CleaningReport
    ) -> None:
        rules = self.config.get("columns", {})
        for column in data.columns:
            rule, _ = self._rule_for_column(column, rules)
            if rule.get("required"):
                count = int(data[column].isna().sum())
                if count:
                    report.warnings.append(
                        f"Cột bắt buộc {column} còn thiếu {count} giá trị."
                    )

    def _drop_empty(self, data: pd.DataFrame, report: CleaningReport) -> None:
        options = self.config.get("drop", {})
        if options.get("empty_columns"):
            empty = [str(column) for column in data.columns if data[column].isna().all()]
            if empty:
                data.drop(columns=empty, inplace=True)
                report.empty_columns_removed = empty
        if options.get("empty_rows", False):
            before = len(data)
            data.dropna(axis=0, how="all", inplace=True)
            report.empty_rows_removed = before - len(data)

    def _duplicate_subset(self, data: pd.DataFrame) -> list[Any] | None:
        options = self.config.get("duplicates", {})
        raw_subset = options.get("subset")
        if isinstance(raw_subset, str):
            subset = [raw_subset]
        elif raw_subset is None:
            subset = None
        elif isinstance(raw_subset, (list, tuple)):
            subset = list(raw_subset)
        else:
            raise ConfigError("duplicates.subset phải là tên cột hoặc danh sách tên cột.")
        if subset:
            resolved: list[Any] = []
            missing: list[Any] = []
            for requested in subset:
                if requested in data.columns:
                    resolved.append(requested)
                    continue
                candidates = [
                    column for column in data.columns if _key(column) == _key(requested)
                ]
                if len(candidates) == 1:
                    resolved.append(candidates[0])
                else:
                    missing.append(requested)
            if missing:
                raise ConfigError(f"Cột kiểm tra trùng không tồn tại: {missing}")
            subset = resolved
        return subset

    def _audit_duplicates(self, data: pd.DataFrame, report: CleaningReport) -> None:
        subset = self._duplicate_subset(data)
        report.duplicates_detected = int(data.duplicated().sum())
        report.duplicates_detected_by_subset = int(
            data.duplicated(subset=subset).sum()
        )

    def _drop_duplicates(
        self, data: pd.DataFrame, report: CleaningReport
    ) -> pd.DataFrame:
        options = self.config.get("duplicates", {})
        should_drop = bool(options.get("enabled", False)) or options.get(
            "action", "report_only"
        ) == "drop"
        if not should_drop:
            return data
        subset = self._duplicate_subset(data)
        before = len(data)
        configured_keep = options.get("keep", "first")
        keep: Literal["first", "last", "most_complete"] | bool
        keep = (
            "most_complete"
            if configured_keep == "keep-most-complete"
            else cast(Literal["first", "last", "most_complete", False], configured_keep)
        )
        result = deduplicate_frame(data, subset=subset, keep=keep)
        report.duplicates_removed = before - len(result)
        return result

    def _audit_outliers(self, data: pd.DataFrame, report: CleaningReport) -> None:
        options = self.config.get("outliers", {})
        selected = options.get("columns")
        selected_keys = {_key(name) for name in selected or []}
        if selected is not None:
            available_keys = {_key(column) for column in data.columns}
            missing = [name for name in selected if _key(name) not in available_keys]
            if missing:
                raise ConfigError(f"Cột phát hiện outlier không tồn tại: {missing}")
        rules = self.config.get("columns", {})
        for column in data.columns:
            rule, _ = self._rule_for_column(column, rules)
            column_methods = rule.get("outlier_methods")
            enabled = bool(options.get("enabled", False))
            if selected is not None:
                enabled = _key(column) in selected_keys
            if column_methods is None and not enabled:
                continue
            methods = column_methods if column_methods is not None else options.get(
                "methods", ["iqr"]
            )
            if isinstance(methods, str):
                methods = [methods]
            numeric = pd.to_numeric(data[column], errors="coerce").dropna()
            if numeric.empty:
                continue
            findings: dict[str, int] = {}
            if "iqr" in methods and len(numeric) >= 4:
                first = float(numeric.quantile(0.25))
                third = float(numeric.quantile(0.75))
                spread = third - first
                multiplier = float(options.get("iqr_multiplier", 1.5))
                findings["iqr"] = int(
                    (
                        (numeric < first - multiplier * spread)
                        | (numeric > third + multiplier * spread)
                    ).sum()
                )
            if "zscore" in methods and len(numeric) >= 2:
                deviation = float(numeric.std(ddof=0))
                if deviation == 0:
                    findings["zscore"] = 0
                else:
                    mean = float(numeric.mean())
                    threshold = float(options.get("zscore_threshold", 3.0))
                    findings["zscore"] = int(
                        (((numeric.astype(float) - mean).abs() / deviation) > threshold).sum()
                    )
            if findings:
                report.outliers_by_column[str(column)] = findings

    def _apply_domain_rules(
        self, data: pd.DataFrame, report: CleaningReport
    ) -> None:
        options = self.config.get("domain_rules", {})
        if not options.get("enabled", False):
            return
        result = validate_domain_rules(data, self.profile, config=options)
        report.domain_rule_violations.update(result.violations)
        failed = sum(result.violations.values())
        report.validation_failed += failed
        if failed:
            report.warnings.append(
                f"Phát hiện {failed} vi phạm rule nghiệp vụ ở profile {self.profile}."
            )


@overload
def clean_dataframe(
    frame: pd.DataFrame,
    *,
    profile: str | None = None,
    config: str | Mapping[str, Any] | None = None,
    return_report: Literal[False] = False,
    inplace: bool = False,
) -> pd.DataFrame: ...


@overload
def clean_dataframe(
    frame: pd.DataFrame,
    *,
    profile: str | None = None,
    config: str | Mapping[str, Any] | None = None,
    return_report: Literal[True],
    inplace: bool = False,
) -> CleaningResult: ...


def clean_dataframe(
    frame: pd.DataFrame,
    *,
    profile: str | None = None,
    config: str | Mapping[str, Any] | None = None,
    return_report: bool = False,
    inplace: bool = False,
) -> pd.DataFrame | CleaningResult:
    """Convenience function for one-shot cleaning.

    Set ``return_report=True`` to receive :class:`CleaningResult`; otherwise
    only the cleaned DataFrame is returned.
    """

    result = DataCleaner(profile=profile, config=config).clean(frame, inplace=inplace)
    return result if return_report else result.data
