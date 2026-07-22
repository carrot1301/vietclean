"""Configuration loading, validation, and starter templates."""

from __future__ import annotations

import json
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from .exceptions import ConfigurationError


DEFAULT_MISSING_TOKENS = [
    "",
    "-",
    "--",
    "---",
    "?",
    "n/a",
    "na",
    "n.a",
    "#n/a",
    "#na",
    "null",
    "none",
    "nil",
    "nan",
    "missing",
    "unknown",
    "not available",
    "không có",
    "khong co",
    "chưa có",
    "chua co",
    "không rõ",
    "khong ro",
    "không xác định",
    "khong xac dinh",
]


BASE_CONFIG: dict[str, Any] = {
    "version": 1,
    "strict": False,
    "locale": "vi_VN",
    "text": {
        "unicode_form": "NFC",
        "repair_mojibake": True,
        "mojibake_confidence_threshold": 0.90,
        "remove_invisible": True,
        "line_breaks": "keep",
        "trim": True,
        "collapse_whitespace": True,
        "tabs_to_spaces": True,
        "remove_joiners": False,
    },
    "missing": {
        "tokens": DEFAULT_MISSING_TOKENS,
        "case_sensitive": False,
        "accent_sensitive": False,
        "strip_before_match": True,
        "default_strategy": "keep",
    },
    "columns": {},
    "auto_types": True,
    "type_conversion": {
        "minimum_success_rate": 0.80,
        "day_first": True,
        "decimal_separator": ",",
        "thousands_separator": ".",
        "currency": "VND",
        "timezone_policy": "preserve",
        "min_year": None,
        "max_year": None,
        "excel_serial": True,
        "invalid": "keep",
        "boolean_true": ["1", "true", "yes", "y", "có", "co", "đúng", "dung", "active"],
        "boolean_false": [
            "0",
            "false",
            "no",
            "n",
            "không",
            "khong",
            "sai",
            "inactive",
        ],
    },
    "column_names": {
        "style": "preserve",
        "strip": True,
        "line_breaks": "space",
        "deduplicate": True,
        "lowercase": False,
        "snake_case": False,
    },
    "drop": {"empty_rows": False, "empty_columns": False},
    "duplicates": {
        "enabled": False,
        "action": "report_only",
        "subset": None,
        "keep": "first",
    },
    "outliers": {
        "enabled": False,
        "methods": ["iqr"],
        "columns": None,
        "iqr_multiplier": 1.5,
        "zscore_threshold": 3.0,
        "action": "report_only",
    },
    "domain_rules": {
        "enabled": False,
        "mode": "report_only",
        "absolute_tolerance": 1.0,
        "relative_tolerance": 0.001,
    },
    "quality": {
        "threshold": None,
        "weights": {
            "completeness": 0.30,
            "validity": 0.25,
            "uniqueness": 0.20,
            "consistency": 0.15,
            "integrity": 0.10,
        },
    },
}


class ConfigError(ConfigurationError):
    """Raised for an invalid user configuration."""


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge mappings without mutating either input."""

    result = deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_config(config: str | Path | Mapping[str, Any] | None) -> dict[str, Any]:
    """Load a non-executable TOML/JSON file or clone an in-memory mapping."""

    if config is None:
        return {}
    if isinstance(config, Mapping):
        return deepcopy(dict(config))
    path = Path(config)
    try:
        if path.suffix.casefold() == ".toml":
            loaded = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        else:
            loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Không tìm thấy file cấu hình: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"JSON không hợp lệ tại dòng {exc.lineno}, cột {exc.colno}: {path}"
        ) from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"TOML không hợp lệ trong {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ConfigError("Cấu hình phải là một object/table ở cấp cao nhất.")
    return loaded


def validate_config(config: Mapping[str, Any]) -> None:
    """Fail early for options that could otherwise produce surprising output."""

    version = config.get("version", 1)
    if version != 1:
        raise ConfigError(f"Config version không được hỗ trợ: {version!r}; hiện chỉ hỗ trợ 1.")
    if not isinstance(config.get("strict", False), bool):
        raise ConfigError("strict phải là true hoặc false.")
    sections = {
        name: config.get(name, {})
        for name in (
            "text",
            "missing",
            "columns",
            "type_conversion",
            "column_names",
            "drop",
            "duplicates",
            "outliers",
            "domain_rules",
            "quality",
        )
    }
    for name, value in sections.items():
        if not isinstance(value, Mapping):
            raise ConfigError(f"{name} phải là một object/table.")
    if not isinstance(config.get("auto_types", True), bool):
        raise ConfigError("auto_types phải là true hoặc false.")
    boolean_options = {
        "text": (
            "repair_mojibake",
            "repair_vietnamese_mojibake",
            "remove_invisible",
            "trim",
            "collapse_whitespace",
            "normalize_spaces",
            "tabs_to_spaces",
            "remove_joiners",
            "normalize_non_breaking_space",
        ),
        "missing": ("case_sensitive", "accent_sensitive", "strip_before_match"),
        "type_conversion": ("excel_serial",),
        "column_names": ("strip", "deduplicate", "lowercase", "snake_case"),
        "drop": ("empty_rows", "empty_columns"),
        "duplicates": ("enabled",),
        "outliers": ("enabled",),
        "domain_rules": ("enabled",),
    }
    for section_name, keys in boolean_options.items():
        section = sections[section_name]
        for key in keys:
            if key in section and not isinstance(section[key], bool):
                raise ConfigError(f"{section_name}.{key} phải là true hoặc false.")
    if config.get("strict", False):
        # profile/preset are consumed before validation by DataCleaner.
        allowed_top_level = set(BASE_CONFIG)
        unknown = set(config) - allowed_top_level
        if unknown:
            raise ConfigError(f"Key config không xác định trong strict mode: {sorted(unknown)}")
        allowed_sections = {
            "text": {
                "unicode_form",
                "repair_mojibake",
                "repair_vietnamese_mojibake",
                "remove_invisible",
                "line_breaks",
                "trim",
                "collapse_whitespace",
                "normalize_spaces",
                "normalize_non_breaking_space",
                "whitespace_mode",
                "line_break_mode",
                "tabs_to_spaces",
                "remove_joiners",
                "mojibake_confidence_threshold",
            },
            "missing": {
                "tokens",
                "case_sensitive",
                "accent_sensitive",
                "strip_before_match",
                "default_strategy",
            },
            "type_conversion": {
                "minimum_success_rate",
                "day_first",
                "decimal_separator",
                "thousands_separator",
                "currency",
                "timezone_policy",
                "min_year",
                "max_year",
                "invalid",
                "excel_serial",
                "boolean_true",
                "boolean_false",
            },
            "column_names": {
                "style",
                "strip",
                "line_breaks",
                "deduplicate",
                "lowercase",
                "snake_case",
            },
            "drop": {"empty_rows", "empty_columns"},
            "duplicates": {"enabled", "action", "subset", "keep"},
            "outliers": {
                "enabled",
                "methods",
                "columns",
                "iqr_multiplier",
                "zscore_threshold",
                "action",
            },
            "domain_rules": {
                "enabled",
                "mode",
                "absolute_tolerance",
                "relative_tolerance",
                "payment_methods",
                "order_statuses",
                "payment_statuses",
                "shipping_statuses",
                "kpi_scale",
                "currencies",
                "discount_mode",
                "tax_mode",
                "debit_credit_rule",
                "finance_amount_formula",
            },
            "quality": {"threshold", "weights"},
        }
        for name, allowed in allowed_sections.items():
            nested_unknown = set(sections[name]) - allowed
            if nested_unknown:
                raise ConfigError(
                    f"Key {name} không xác định trong strict mode: {sorted(nested_unknown)}"
                )
    text_options = config.get("text", {})
    line_breaks = text_options.get(
        "whitespace_mode",
        text_options.get("line_break_mode", text_options.get("line_breaks", "keep")),
    )
    valid_whitespace = {
        "preserve",
        "trim",
        "normalize_spaces",
        "single_line",
        "canonical_multiline",
        "keep",
        "space",
        "remove",
    }
    if line_breaks not in valid_whitespace:
        raise ConfigError("text whitespace mode không hợp lệ.")
    column_name_options = config.get("column_names", {})
    if column_name_options.get("style", "preserve") not in {
        "snake_case",
        "lower_snake_case",
        "upper_snake_case",
        "preserve",
    }:
        raise ConfigError("column_names.style không hợp lệ.")
    if column_name_options.get("line_breaks", "space") not in valid_whitespace:
        raise ConfigError("column_names.line_breaks không hợp lệ.")
    confidence = text_options.get("mojibake_confidence_threshold", 0.9)
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not 0 <= confidence <= 1
    ):
        raise ConfigError("text.mojibake_confidence_threshold phải nằm trong [0, 1].")
    invalid = config.get("type_conversion", {}).get("invalid", "keep")
    if invalid not in {"keep", "missing", "raise"}:
        raise ConfigError("type_conversion.invalid phải là keep, missing hoặc raise.")
    duplicate_options = config.get("duplicates", {})
    keep = duplicate_options.get("keep", "first")
    if keep not in {"first", "last", False, "most_complete", "keep-most-complete"}:
        raise ConfigError(
            "duplicates.keep phải là first, last, false hoặc most_complete."
        )
    if duplicate_options.get("action", "report_only") not in {"report_only", "drop"}:
        raise ConfigError("duplicates.action phải là report_only hoặc drop.")
    supported_missing_strategies = {
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
    default_missing = config.get("missing", {}).get("default_strategy", "keep")
    if default_missing not in supported_missing_strategies:
        raise ConfigError(f"missing.default_strategy={default_missing!r} không hợp lệ.")
    rate = config.get("type_conversion", {}).get("minimum_success_rate", 0.8)
    if not isinstance(rate, (int, float)) or not 0 <= rate <= 1:
        raise ConfigError("type_conversion.minimum_success_rate phải nằm trong [0, 1].")
    conversion = config.get("type_conversion", {})
    day_first = conversion.get("day_first", True)
    if day_first is not None and not isinstance(day_first, bool):
        raise ConfigError("type_conversion.day_first phải là true, false hoặc null.")
    if conversion.get("decimal_separator", ",") not in {",", "."}:
        raise ConfigError("type_conversion.decimal_separator phải là ',' hoặc '.'.")
    if conversion.get("thousands_separator", ".") not in {",", ".", " ", ""}:
        raise ConfigError(
            "type_conversion.thousands_separator phải là ',', '.', space hoặc chuỗi rỗng."
        )
    if (
        conversion.get("thousands_separator", ".")
        and conversion.get("decimal_separator", ",")
        == conversion.get("thousands_separator", ".")
    ):
        raise ConfigError("decimal_separator và thousands_separator phải khác nhau.")
    supported_currencies = {
        "vnd",
        "vnđ",
        "đ",
        "usd",
        "eur",
        "gbp",
        "jpy",
        "cny",
        "rmb",
    }
    global_currency = conversion.get("currency", "VND")
    if str(global_currency).casefold() not in supported_currencies:
        raise ConfigError(f"currency={global_currency!r} không được hỗ trợ.")
    if conversion.get("timezone_policy", "preserve") not in {
        "preserve",
        "naive",
        "utc",
        "naive_utc",
    }:
        raise ConfigError(
            "type_conversion.timezone_policy phải là preserve, naive, utc hoặc naive_utc."
        )
    for key in ("boolean_true", "boolean_false"):
        values = conversion.get(key, [])
        if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
            raise ConfigError(f"type_conversion.{key} phải là danh sách chuỗi.")
        if not all(isinstance(value, str) for value in values):
            raise ConfigError(f"type_conversion.{key} chỉ được chứa chuỗi.")
    true_values = {value.casefold() for value in conversion.get("boolean_true", [])}
    false_values = {value.casefold() for value in conversion.get("boolean_false", [])}
    if true_values & false_values:
        raise ConfigError("boolean_true và boolean_false không được giao nhau.")

    outliers = config.get("outliers", {})
    methods = outliers.get("methods", ["iqr"])
    if isinstance(methods, str):
        methods = [methods]
    if not isinstance(methods, (list, tuple)) or any(
        method not in {"iqr", "zscore"} for method in methods
    ):
        raise ConfigError("outliers.methods chỉ hỗ trợ iqr và zscore.")
    if outliers.get("action", "report_only") != "report_only":
        raise ConfigError("outliers.action hiện chỉ hỗ trợ report_only để tránh đổi dữ liệu.")
    for key in ("iqr_multiplier", "zscore_threshold"):
        value = outliers.get(key, 1.5 if key == "iqr_multiplier" else 3.0)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or value <= 0
        ):
            raise ConfigError(f"outliers.{key} phải là số dương.")
    selected_columns = outliers.get("columns")
    if selected_columns is not None and (
        isinstance(selected_columns, (str, bytes))
        or not isinstance(selected_columns, (list, tuple))
        or not all(isinstance(name, str) for name in selected_columns)
    ):
        raise ConfigError("outliers.columns phải là danh sách tên cột hoặc null.")

    domain = config.get("domain_rules", {})
    if domain.get("mode", "report_only") != "report_only":
        raise ConfigError("domain_rules.mode hiện chỉ hỗ trợ report_only.")
    for key in ("absolute_tolerance", "relative_tolerance"):
        value = domain.get(key, 1.0 if key == "absolute_tolerance" else 0.001)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or value < 0
        ):
            raise ConfigError(f"domain_rules.{key} phải là số không âm.")
    if domain.get("discount_mode", "amount") not in {"amount", "rate"}:
        raise ConfigError("domain_rules.discount_mode phải là amount hoặc rate.")
    if domain.get("tax_mode", "amount") not in {"amount", "rate"}:
        raise ConfigError("domain_rules.tax_mode phải là amount hoặc rate.")
    if domain.get("debit_credit_rule", "one_sided") not in {
        "one_sided",
        "disabled",
    }:
        raise ConfigError("domain_rules.debit_credit_rule không hợp lệ.")
    if domain.get("finance_amount_formula", "debit_minus_credit") not in {
        "debit_minus_credit",
        "absolute_difference",
        "disabled",
    }:
        raise ConfigError("domain_rules.finance_amount_formula không hợp lệ.")
    if domain.get("kpi_scale", "fraction") not in {"fraction", "percent"}:
        raise ConfigError("domain_rules.kpi_scale phải là fraction hoặc percent.")

    quality = config.get("quality", {})
    threshold = quality.get("threshold")
    if threshold is not None and (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or not 0 <= threshold <= 100
    ):
        raise ConfigError("quality.threshold phải nằm trong [0, 100] hoặc null.")
    weights = quality.get("weights", {})
    if not isinstance(weights, Mapping):
        raise ConfigError("quality.weights phải là object/table.")
    expected_weights = {
        "completeness",
        "validity",
        "uniqueness",
        "consistency",
        "integrity",
    }
    unknown_weights = set(weights) - expected_weights
    if unknown_weights:
        raise ConfigError(f"quality.weights không xác định: {sorted(unknown_weights)}")
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value < 0
        for value in weights.values()
    ):
        raise ConfigError("Mỗi quality weight phải là số không âm.")
    if not weights or sum(float(value) for value in weights.values()) <= 0:
        raise ConfigError("Tổng quality.weights phải lớn hơn 0.")
    min_year = conversion.get("min_year")
    max_year = conversion.get("max_year")
    if min_year is not None and (not isinstance(min_year, int) or isinstance(min_year, bool)):
        raise ConfigError("type_conversion.min_year phải là số nguyên hoặc null.")
    if max_year is not None and (not isinstance(max_year, int) or isinstance(max_year, bool)):
        raise ConfigError("type_conversion.max_year phải là số nguyên hoặc null.")
    if min_year is not None and max_year is not None and min_year > max_year:
        raise ConfigError("type_conversion.min_year không được lớn hơn max_year.")
    columns = sections["columns"]
    allowed_column_keys = {
        "type",
        "invalid",
        "required",
        "missing_tokens",
        "default_country",
        "decimal_comma",
        "decimal_separator",
        "thousands_separator",
        "percent_as_fraction",
        "bare_percentage",
        "currency",
        "excel_serial",
        "format",
        "day_first",
        "min",
        "max",
        "regex",
        "allowed",
        "map",
        "replace",
        "case",
        "missing_strategy",
        "flag_column",
        "fill",
        "group_by",
        "fill_strategy",
        "whitespace_mode",
        "line_break_mode",
        "true_values",
        "false_values",
        "outlier_methods",
    }
    semantic_types = {
        "text",
        "identifier",
        "email",
        "phone",
        "integer",
        "number",
        "percentage",
        "currency",
        "date",
        "datetime",
        "boolean",
        "category",
        "address",
    }
    for column, rule in columns.items():
        if not isinstance(rule, Mapping):
            raise ConfigError(f"Rule của cột {column!r} phải là object/table.")
        if config.get("strict", False):
            unknown_rule_keys = set(rule) - allowed_column_keys
            if unknown_rule_keys:
                raise ConfigError(
                    f"Key rule không xác định ở cột {column!r}: {sorted(unknown_rule_keys)}"
                )
        semantic = rule.get("type")
        if semantic is not None and str(semantic).casefold() not in semantic_types:
            raise ConfigError(f"type={semantic!r} không được hỗ trợ ở cột {column!r}.")
        strategy = rule.get("missing_strategy")
        if strategy is not None and strategy not in supported_missing_strategies:
            raise ConfigError(f"missing_strategy={strategy!r} không hợp lệ ở cột {column!r}.")
        if str(semantic).casefold() == "identifier" and strategy == "fill_mean":
            raise ConfigError(f"Không được dùng fill_mean cho mã định danh {column!r}.")
        rule_invalid = rule.get("invalid", invalid)
        if rule_invalid not in {"keep", "missing", "raise"}:
            raise ConfigError(f"invalid={rule_invalid!r} không hợp lệ ở cột {column!r}.")
        if "required" in rule and not isinstance(rule["required"], bool):
            raise ConfigError(f"required phải là boolean ở cột {column!r}.")
        for key in ("decimal_comma", "percent_as_fraction", "excel_serial"):
            if key in rule and not isinstance(rule[key], bool):
                raise ConfigError(f"{key} phải là boolean ở cột {column!r}.")
        if "day_first" in rule and rule["day_first"] is not None and not isinstance(
            rule["day_first"], bool
        ):
            raise ConfigError(f"day_first phải là boolean hoặc null ở cột {column!r}.")
        column_mode = rule.get("whitespace_mode", rule.get("line_break_mode"))
        if column_mode is not None and column_mode not in valid_whitespace:
            raise ConfigError(f"whitespace mode không hợp lệ ở cột {column!r}.")
        for key in ("true_values", "false_values"):
            if key in rule and (
                isinstance(rule[key], (str, bytes))
                or not isinstance(rule[key], (list, tuple))
                or not all(isinstance(value, str) for value in rule[key])
            ):
                raise ConfigError(f"{key} phải là danh sách chuỗi ở cột {column!r}.")
        if "outlier_methods" in rule:
            column_methods = rule["outlier_methods"]
            if isinstance(column_methods, str):
                column_methods = [column_methods]
            if not isinstance(column_methods, (list, tuple)) or any(
                method not in {"iqr", "zscore"} for method in column_methods
            ):
                raise ConfigError(
                    f"outlier_methods chỉ hỗ trợ iqr và zscore ở cột {column!r}."
                )
        if "regex" in rule and not isinstance(rule["regex"], str):
            raise ConfigError(f"regex phải là chuỗi ở cột {column!r}.")
        if rule.get("bare_percentage", "reject") not in {"reject", "fraction", "percent"}:
            raise ConfigError(
                f"bare_percentage phải là reject, fraction hoặc percent ở cột {column!r}."
            )
        selected_currency = rule.get("currency", conversion.get("currency", "VND"))
        if str(selected_currency).casefold() not in supported_currencies:
            raise ConfigError(f"currency={selected_currency!r} không được hỗ trợ.")
        column_decimal = rule.get("decimal_separator", conversion.get("decimal_separator", ","))
        column_thousands = rule.get(
            "thousands_separator", conversion.get("thousands_separator", ".")
        )
        if column_decimal not in {",", "."}:
            raise ConfigError(f"decimal_separator không hợp lệ ở cột {column!r}.")
        if column_thousands not in {",", ".", " ", ""}:
            raise ConfigError(f"thousands_separator không hợp lệ ở cột {column!r}.")
        if column_thousands and column_decimal == column_thousands:
            raise ConfigError(
                f"decimal_separator và thousands_separator trùng ở cột {column!r}."
            )


def starter_config(profile: str = "generic") -> dict[str, Any]:
    """Return an annotated-by-example (but valid JSON) starter configuration."""

    return {
        "version": 1,
        "profile": profile,
        "text": {"line_breaks": "keep", "repair_mojibake": True},
        "duplicates": {"enabled": False},
        "columns": {
            "email": {"type": "email", "invalid": "missing"},
            "số điện thoại": {"type": "phone", "invalid": "keep"},
            "doanh thu": {"type": "currency", "invalid": "keep", "min": 0},
            "ngày tạo": {"type": "date", "invalid": "keep"},
        },
    }


def starter_toml(profile: str = "generic") -> str:
    """Return a dependency-free TOML starter template."""

    safe_profile = profile.replace("\\", "\\\\").replace('"', '\\"')
    return f'''version = 1
profile = "{safe_profile}"
strict = true
locale = "vi_VN"

[text]
unicode_form = "NFC"
line_breaks = "keep"
repair_mojibake = true
remove_invisible = true

[duplicates]
enabled = false
keep = "first"

[columns.email]
type = "email"
invalid = "missing"
required = true

[columns."số điện thoại"]
type = "phone"
invalid = "keep"

[columns."doanh thu"]
type = "currency"
invalid = "keep"
min = 0

[columns."ngày tạo"]
type = "date"
invalid = "keep"
'''
