from decimal import Decimal

import pandas as pd
import pytest

from vietclean.config import ConfigError
from vietclean.pipeline import CleaningError, DataCleaner, clean_dataframe
from vietclean.report import CleaningResult


def test_missing_and_vietnamese_text_are_cleaned_without_mutating_input() -> None:
    frame = pd.DataFrame(
        {
            "id": [1, 2],
            "ghi chú": ["  Tiáº¿ng \r\n Viá»‡t\u200b  ", " CHƯA   CÓ "],
        }
    )

    result = DataCleaner(config={"auto_types": False}).clean(frame)

    assert frame.loc[0, "ghi chú"] == "  Tiáº¿ng \r\n Viá»‡t\u200b  "
    assert result.data.loc[0, "ghi chú"] == "Tiếng\nViệt"
    assert pd.isna(result.data.loc[1, "ghi chú"])
    assert result.report.missing_before["ghi chú"] == 0
    assert result.report.missing_after["ghi chú"] == 1
    assert result.report.changed_by_column["ghi chú"] == 2


def test_explicit_types_are_accent_insensitive_and_honor_invalid_policy() -> None:
    frame = pd.DataFrame(
        {
            "Doanh số": ["1.250.000 ₫", "không hợp lệ"],
            "Đăng ký": ["có", "không"],
            "Liên hệ": [" User@EXAMPLE.COM ", "sai địa chỉ"],
        }
    )
    config = {
        "columns": {
            "DOANH SO": {"type": "currency", "invalid": "missing"},
            "dang ky": {"type": "boolean", "invalid": "raise"},
            "lien he": {"type": "email", "invalid": "missing"},
        }
    }

    result = DataCleaner(config=config).clean(frame)

    assert result.data.loc[0, "Doanh số"] == Decimal("1250000")
    assert pd.isna(result.data.loc[1, "Doanh số"])
    assert list(result.data["Đăng ký"]) == [True, False]
    assert result.data.loc[0, "Liên hệ"] == "User@example.com"
    assert pd.isna(result.data.loc[1, "Liên hệ"])
    assert result.report.semantic_types == {
        "Doanh số": "currency",
        "Đăng ký": "boolean",
        "Liên hệ": "email",
    }
    assert result.report.invalid_by_column == {"Doanh số": 1, "Liên hệ": 1}


def test_ecommerce_profile_infers_common_vietnamese_columns_conservatively() -> None:
    frame = pd.DataFrame(
        {
            "Phí vận chuyển": ["25.000 ₫", "30.000 ₫"],
            "Số lượng đặt": ["2", "3"],
            "Email": ["A@EXAMPLE.COM", "b@example.com"],
            "Trường lạ": ["001", "002"],
        }
    )

    result = DataCleaner(profile="ecommerce").clean(frame)

    assert list(result.data["Phí vận chuyển"]) == [Decimal("25000"), Decimal("30000")]
    assert list(result.data["Số lượng đặt"]) == [Decimal("2"), Decimal("3")]
    assert list(result.data["Email"]) == ["A@example.com", "b@example.com"]
    assert list(result.data["Trường lạ"]) == ["001", "002"]
    assert result.report.semantic_types == {
        "Phí vận chuyển": "currency",
        "Số lượng đặt": "integer",
        "Email": "email",
    }


def test_inferred_conversion_is_skipped_below_success_threshold() -> None:
    frame = pd.DataFrame({"Email": ["good@example.com", "not an email"]})

    result = DataCleaner().clean(frame)

    assert list(result.data["Email"]) == ["good@example.com", "not an email"]
    assert result.report.semantic_types["Email"] == "email"
    assert "Email" not in result.report.invalid_by_column
    assert any("50%" in warning for warning in result.report.warnings)


def test_mixed_vietnamese_and_iso_dates_work_across_pandas_versions() -> None:
    frame = pd.DataFrame(
        {
            "id": [1, 2, 3],
            "Ngày giao": ["31/12/2025", "2026-01-02", "không phải ngày"],
        }
    )

    result = DataCleaner(
        config={
            "columns": {
                "Ngày giao": {"type": "date", "invalid": "missing"}
            }
        }
    ).clean(frame)

    assert result.data.loc[0, "Ngày giao"] == pd.Timestamp("2025-12-31")
    assert result.data.loc[1, "Ngày giao"] == pd.Timestamp("2026-01-02")
    assert pd.isna(result.data.loc[2, "Ngày giao"])
    assert result.report.invalid_by_column["Ngày giao"] == 1


def test_excel_serial_date_is_supported_only_for_date_columns() -> None:
    frame = pd.DataFrame({"Ngày giao": [45292], "Mã": [45292]})

    result = DataCleaner(
        config={
            "auto_types": False,
            "columns": {"Ngày giao": {"type": "date", "invalid": "raise"}},
        }
    ).clean(frame)

    assert result.data.loc[0, "Ngày giao"] == pd.Timestamp("2024-01-01")
    assert result.data.loc[0, "Mã"] == 45292


def test_duplicates_are_preserved_by_default_and_removed_only_when_enabled() -> None:
    frame = pd.DataFrame({"id": [1, 1, 2], "value": ["a", "b", "c"]})

    default_result = DataCleaner(config={"auto_types": False}).clean(frame)
    enabled_result = DataCleaner(
        config={
            "auto_types": False,
            "duplicates": {"enabled": True, "subset": "id", "keep": "first"},
        }
    ).clean(frame)

    assert len(default_result.data) == 3
    assert default_result.report.duplicates_removed == 0
    assert list(enabled_result.data["value"]) == ["a", "c"]
    assert enabled_result.report.duplicates_removed == 1
    assert enabled_result.report.rows_before == 3
    assert enabled_result.report.rows_after == 2


def test_report_change_tracking_handles_duplicate_index_labels() -> None:
    frame = pd.DataFrame(
        {"id": [1, 2], "note": ["  A  ", "B\n C"]},
        index=[7, 7],
    )

    result = clean_dataframe(
        frame,
        config={"auto_types": False},
        return_report=True,
    )

    assert isinstance(result, CleaningResult)
    assert list(result.data["note"]) == ["A", "B\nC"]
    assert result.report.changed_by_column["note"] == 2
    assert result.report.cells_changed == 2
    assert result.report.rows_before == result.report.rows_after == 2
    assert result.report.columns_before == result.report.columns_after == 2
    assert result.report.finished_at is not None
    assert result.report.to_dict()["profile"] == "generic"


def test_column_name_deduplication_handles_existing_suffixes() -> None:
    frame = pd.DataFrame([[1, 2, 3]], columns=["x", "x_2", "x"])

    cleaned = clean_dataframe(frame, config={"auto_types": False})

    assert list(cleaned.columns) == ["x", "x_2", "x_3"]


def test_duplicate_column_names_fail_safely_when_deduplication_is_disabled() -> None:
    frame = pd.DataFrame([[1, 2]], columns=["x", "x"])

    with pytest.raises(ConfigError, match="deduplicate"):
        clean_dataframe(
            frame,
            config={
                "auto_types": False,
                "column_names": {"deduplicate": False},
            },
        )


@pytest.mark.parametrize(
    "config",
    [
        {"text": {"line_breaks": "explode"}},
        {"type_conversion": {"minimum_success_rate": 1.5}},
        {"duplicates": {"keep": "middle"}},
    ],
)
def test_unsafe_global_config_is_rejected_before_cleaning(config: dict) -> None:
    with pytest.raises(ConfigError):
        DataCleaner(config=config)


def test_invalid_column_policy_and_regex_raise_clear_config_errors() -> None:
    frame = pd.DataFrame({"x": ["ok"]})

    with pytest.raises(ConfigError, match="invalid='erase'"):
        clean_dataframe(
            frame,
            config={"auto_types": False, "columns": {"x": {"invalid": "erase"}}},
        )
    with pytest.raises(ConfigError, match="regex"):
        clean_dataframe(
            frame,
            config={"auto_types": False, "columns": {"x": {"regex": "["}}},
        )

    with pytest.raises(ConfigError, match="ReDoS"):
        clean_dataframe(
            pd.DataFrame({"x": ["a" * 100]}),
            config={"auto_types": False, "columns": {"x": {"regex": "(a+)+$"}}},
        )


def test_explicit_raise_policy_does_not_silently_keep_bad_values() -> None:
    frame = pd.DataFrame({"amount": ["100", "bad"]})

    with pytest.raises(CleaningError, match="amount"):
        clean_dataframe(
            frame,
            config={
                "columns": {"amount": {"type": "currency", "invalid": "raise"}}
            },
        )


def test_input_config_is_copied_and_explicit_profile_takes_precedence() -> None:
    config = {"profile": "finance", "auto_types": False}

    cleaner = DataCleaner(profile="generic", config=config)

    assert config == {"profile": "finance", "auto_types": False}
    assert cleaner.profile == "generic"
    assert "profile" not in cleaner.config


def test_percentage_profile_and_column_specific_missing_tokens() -> None:
    frame = pd.DataFrame(
        {
            "conversion_rate": ["15,5%", "~"],
            "note": ["~", "kept"],
        }
    )
    result = DataCleaner(
        profile="marketing",
        config={"columns": {"conversion_rate": {"missing_tokens": ["~"]}}},
    ).clean(frame)

    assert result.data.loc[0, "conversion_rate"] == Decimal("0.155")
    assert pd.isna(result.data.loc[1, "conversion_rate"])
    assert result.data.loc[0, "note"] == "~"
    assert result.report.semantic_types["conversion_rate"] == "percentage"


def test_percentage_and_currency_units_never_mix_silently() -> None:
    frame = pd.DataFrame(
        {
            "conversion_rate": ["15%", "15", "0.15"],
            "amount": ["1.000 VND", "1 USD", "1000"],
        }
    )
    result = DataCleaner(
        config={
            "columns": {
                "conversion_rate": {"type": "percentage", "invalid": "keep"},
                "amount": {"type": "currency", "currency": "VND", "invalid": "keep"},
            }
        }
    ).clean(frame)

    assert result.data["conversion_rate"].tolist() == [Decimal("0.15"), "15", "0.15"]
    assert result.data["amount"].tolist() == [Decimal("1000"), "1 USD", Decimal("1000")]
    assert result.report.invalid_by_column == {"conversion_rate": 2, "amount": 1}

    percent_mode = DataCleaner(
        config={
            "columns": {
                "rate": {
                    "type": "percentage",
                    "bare_percentage": "percent",
                    "invalid": "raise",
                }
            }
        }
    ).clean(pd.DataFrame({"rate": ["15"]}))
    assert percent_mode.data.loc[0, "rate"] == Decimal("0.15")


def test_missing_fill_flag_and_group_median_are_audited() -> None:
    frame = pd.DataFrame(
        {
            "branch": ["A", "A", "B"],
            "amount": [10, None, None],
            "note": [None, "ok", None],
        }
    )
    result = DataCleaner(
        config={
            "auto_types": False,
            "columns": {
                "amount": {"missing_strategy": "group_median", "group_by": "branch"},
                "note": {"missing_strategy": "flag_only"},
            },
        }
    ).clean(frame)

    assert result.data.loc[1, "amount"] == 10
    assert pd.isna(result.data.loc[2, "amount"])
    assert list(result.data["note_was_missing"]) == [True, False, True]
    assert result.report.missing_filled_by_column == {"amount": 1}
    assert result.report.missing_flag_columns_added == ["note_was_missing"]


def test_structural_missing_rules_handle_duplicate_index_labels_positionally() -> None:
    frame = pd.DataFrame(
        {"id": [1, 2, 3], "required": ["ok", None, "ok"], "drop_me": [1, None, 3]},
        index=[7, 7, 8],
    )
    result = DataCleaner(
        config={
            "auto_types": False,
            "columns": {
                "required": {"missing_strategy": "drop_row"},
                "drop_me": {"missing_strategy": "drop_column"},
            },
        }
    ).clean(frame)

    assert list(result.data["id"]) == [1, 3]
    assert list(result.data.index) == [7, 8]
    assert "drop_me" not in result.data
    assert result.report.missing_rows_removed == 1
    assert result.report.missing_columns_removed == ["drop_me"]


def test_cleaner_validates_input_profile_and_normalizes_column_names() -> None:
    with pytest.raises(TypeError, match="DataFrame"):
        DataCleaner().clean([1, 2])  # type: ignore[arg-type]
    with pytest.raises(ConfigError, match="profile"):
        DataCleaner(profile="not-a-profile")

    frame = pd.DataFrame([[1, 2, 3]], columns=[" Đơn Giá / VNĐ ", "", "Đơn Giá / VNĐ"])
    result = DataCleaner(
        config={
            "auto_types": False,
            "column_names": {"lowercase": True, "snake_case": True},
        }
    ).clean(frame)

    assert list(result.data.columns) == ["don_gia_vnd", "column_2", "don_gia_vnd_2"]
    assert result.report.renamed_columns


@pytest.mark.parametrize(
    "pattern",
    ["x" * 257, "a\x00b", r"(a)\1", r"(?=a)a", r"(ab)+", r".*a.*"],
)
def test_user_regex_rejects_common_redos_constructs(pattern: str) -> None:
    with pytest.raises(ConfigError, match="regex"):
        clean_dataframe(
            pd.DataFrame({"x": ["a"]}),
            config={"auto_types": False, "columns": {"x": {"regex": pattern}}},
        )


def test_mapping_case_and_business_validation_rules_are_composable() -> None:
    frame = pd.DataFrame(
        {
            "status": ["new", "DONE", "other"],
            "amount": [-1, 5, 11],
            "code": ["AA", "B2", "bad"],
        }
    )
    result = DataCleaner(
        config={
            "auto_types": False,
            "columns": {
                "status": {
                    "map": {"NEW": "pending", "done": "complete"},
                    "case": "upper",
                    "allowed": ["PENDING", "COMPLETE"],
                    "invalid": "missing",
                },
                "amount": {"min": 0, "max": 10, "invalid": "missing"},
                "code": {"regex": r"[A-Z][A-Z0-9]", "invalid": "missing"},
            },
        }
    ).clean(frame)

    assert result.data["status"].tolist()[:2] == ["PENDING", "COMPLETE"]
    assert pd.isna(result.data.loc[2, "status"])
    assert pd.isna(result.data.loc[0, "amount"])
    assert result.data.loc[1, "amount"] == 5
    assert pd.isna(result.data.loc[2, "amount"])
    assert pd.isna(result.data.loc[2, "code"])
    assert result.report.invalid_by_column == {"status": 1, "amount": 2, "code": 1}


def test_invalid_allowed_rules_fail_before_silently_accepting_values() -> None:
    with pytest.raises(ConfigError, match="danh sách"):
        clean_dataframe(
            pd.DataFrame({"x": ["a"]}),
            config={"auto_types": False, "columns": {"x": {"allowed": "a"}}},
        )
    with pytest.raises(ConfigError, match="scalar"):
        clean_dataframe(
            pd.DataFrame({"x": ["a"]}),
            config={"auto_types": False, "columns": {"x": {"allowed": [["a"]]}}},
        )
    with pytest.raises(CleaningError, match="vi phạm"):
        clean_dataframe(
            pd.DataFrame({"x": [2]}),
            config={
                "auto_types": False,
                "columns": {"x": {"max": 1, "invalid": "raise"}},
            },
        )


def test_all_missing_fill_strategies_are_explicit_and_audited() -> None:
    frame = pd.DataFrame(
        {
            "group": ["A", "A", "A"],
            "zero": [None, 1, None],
            "constant": [None, "x", None],
            "mean": [1, None, 3],
            "median": [1, None, 5],
            "mode": ["a", None, "a"],
            "forward": [1, None, 3],
            "backward": [1, None, 3],
            "group_mode": ["x", None, "x"],
            "short_fill": [None, "ok", None],
            "legacy_mode": ["z", None, "z"],
            "all_missing": [None, None, None],
            "non_numeric": ["x", None, "y"],
        }
    )
    rules = {
        "zero": {"missing_strategy": "fill_zero"},
        "constant": {"missing_strategy": "fill_constant", "fill": "fixed"},
        "mean": {"missing_strategy": "fill_mean"},
        "median": {"missing_strategy": "fill_median"},
        "mode": {"missing_strategy": "fill_mode"},
        "forward": {"missing_strategy": "forward_fill"},
        "backward": {"missing_strategy": "backward_fill"},
        "group_mode": {"missing_strategy": "group_mode", "group_by": "group"},
        "short_fill": {"fill": "short"},
        "legacy_mode": {"fill_strategy": "mode"},
        "all_missing": {"missing_strategy": "fill_mean"},
        "non_numeric": {"missing_strategy": "fill_mean"},
    }

    result = DataCleaner(config={"auto_types": False, "columns": rules}).clean(frame)

    assert result.data.loc[0, "zero"] == 0
    assert result.data.loc[0, "constant"] == "fixed"
    assert result.data.loc[1, "mean"] == 2
    assert result.data.loc[1, "median"] == 3
    assert result.data.loc[1, "mode"] == "a"
    assert result.data.loc[1, "forward"] == 1
    assert result.data.loc[1, "backward"] == 3
    assert result.data.loc[1, "group_mode"] == "x"
    assert result.data.loc[0, "short_fill"] == "short"
    assert result.data.loc[1, "legacy_mode"] == "z"
    assert result.data["all_missing"].isna().all()
    assert pd.isna(result.data.loc[1, "non_numeric"])
    assert result.report.missing_filled_by_column["zero"] == 2


def test_missing_strategy_errors_and_flag_collision_are_clear() -> None:
    frame = pd.DataFrame({"x": [None], "x_was_missing": [False]})
    with pytest.raises(ConfigError, match="đã tồn tại"):
        DataCleaner(
            config={
                "auto_types": False,
                "columns": {"x": {"missing_strategy": "flag_only"}},
            }
        ).clean(frame)
    with pytest.raises(ConfigError, match="key fill"):
        DataCleaner(
            config={
                "auto_types": False,
                "columns": {"x": {"missing_strategy": "fill_constant"}},
            }
        ).clean(pd.DataFrame({"x": [None]}))
    with pytest.raises(ConfigError, match="group_by"):
        DataCleaner(
            config={
                "auto_types": False,
                "columns": {"x": {"missing_strategy": "group_mode"}},
            }
        ).clean(pd.DataFrame({"x": [None]}))


@pytest.mark.parametrize("timezone_policy", ["naive", "utc", "naive_utc"])
def test_datetime_timezone_policies_are_deterministic(timezone_policy: str) -> None:
    result = DataCleaner(
        config={
            "columns": {"when": {"type": "datetime", "invalid": "raise"}},
            "type_conversion": {"timezone_policy": timezone_policy},
        }
    ).clean(pd.DataFrame({"when": ["2026-01-02T12:30:00+07:00"]}))

    value = result.data.loc[0, "when"]
    if timezone_policy == "utc":
        assert str(value.tzinfo) == "UTC"
        assert value.hour == 5
    else:
        assert value.tzinfo is None
        assert value.hour == (12 if timezone_policy == "naive" else 5)


def test_date_format_year_bounds_required_drop_and_duplicate_errors() -> None:
    result = DataCleaner(
        config={
            "columns": {
                "date": {"type": "date", "format": "%d.%m.%Y", "invalid": "missing"},
                "required": {"required": True},
            },
            "type_conversion": {"min_year": 2020, "max_year": 2030},
            "drop": {"empty_rows": True, "empty_columns": True},
            "auto_types": False,
        }
    ).clean(
        pd.DataFrame(
            {
                "date": ["01.02.2026", "01.02.1999", None],
                "required": ["ok", None, None],
                "keep": [1, 2, None],
                "empty": [None, None, None],
            }
        )
    )
    assert result.data.loc[0, "date"] == pd.Timestamp("2026-02-01")
    assert pd.isna(result.data.loc[1, "date"])
    assert "empty" not in result.data
    assert result.report.empty_rows_removed == 1
    assert any("Cột bắt buộc" in warning for warning in result.report.warnings)

    with pytest.raises(ConfigError, match="subset"):
        DataCleaner(
            config={"duplicates": {"enabled": True, "subset": 123}}
        ).clean(pd.DataFrame({"x": [1]}))
    with pytest.raises(ConfigError, match="không tồn tại"):
        DataCleaner(
            config={"duplicates": {"enabled": True, "subset": "missing"}}
        ).clean(pd.DataFrame({"x": [1]}))


def test_required_warning_is_calculated_after_duplicate_removal() -> None:
    frame = pd.DataFrame({"id": [1, 1, 2], "email": [None, None, None]})
    result = DataCleaner(
        config={
            "auto_types": False,
            "duplicates": {"enabled": True, "subset": ["id"]},
            "columns": {"email": {"required": True}},
        }
    ).clean(frame)

    assert result.report.duplicates_removed == 1
    assert any("thiếu 2 giá trị" in warning for warning in result.report.warnings)
