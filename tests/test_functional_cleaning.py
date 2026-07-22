from decimal import Decimal

import pandas as pd
import pytest

from vietclean.config import ConfigError
from vietclean.domain import validate_domain_rules
from vietclean.exceptions import SchemaValidationError
from vietclean.pipeline import DataCleaner
from vietclean.text import (
    analyze_mojibake,
    is_missing,
    normalize_whitespace as normalize_whitespace_scalar,
)
from vietclean.transforms import (
    clean_names,
    coerce_types,
    deduplicate,
    flag_duplicates,
    normalize_column_names,
    normalize_text,
    normalize_unicode as normalize_unicode_frame,
    normalize_whitespace as normalize_whitespace_frame,
    repair_vietnamese_text,
    replace_missing,
    standardize_missing,
    validate_schema,
)


def test_prompt_mojibake_examples_are_exact_idempotent_and_auditable() -> None:
    examples = {
        "Nguyá»…n VÄƒn A": "Nguyễn Văn A",
        "ThÃ nh phá»‘ Há»“ ChÃ­ Minh": "Thành phố Hồ Chí Minh",
        "Cà phê sữa đá": "Cà phê sữa đá",
        "SKU-ÁO-001": "SKU-ÁO-001",
    }
    for source, expected in examples.items():
        decision = analyze_mojibake(source)
        assert decision.value == expected
        assert analyze_mojibake(decision.value).value == expected

    uncertain = analyze_mojibake("Tên bị lỗi �")
    assert uncertain.value == "Tên bị lỗi �"
    assert uncertain.needs_review is True
    assert uncertain.unrepaired is True
    assert uncertain.confidence == 0

    pipeline = DataCleaner(config={"auto_types": False}).clean(
        pd.DataFrame({"text": ["Nguyá»…n VÄƒn A", "Tên bị lỗi �"]})
    )
    assert pipeline.report.encoding_repairs_by_column == {"text": 1}
    assert pipeline.report.mojibake_candidates_by_column == {"text": 1}
    assert pipeline.report.mojibake_review_by_column == {"text": 1}
    assert pipeline.report.mojibake_unrepaired_by_column == {"text": 1}


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("preserve", "  Cà   phê\r\nsữa  "),
        ("trim", "Cà   phê\r\nsữa"),
        ("normalize_spaces", "Cà phê\nsữa"),
        ("single_line", "Cà phê sữa"),
        ("canonical_multiline", "Cà phê\n\nsữa"),
    ],
)
def test_all_prompt_whitespace_modes(mode: str, expected: str) -> None:
    source = "  Cà   phê\r\nsữa  " if mode != "canonical_multiline" else "Cà phê\n\n\n\nsữa"
    assert normalize_whitespace_scalar(source, mode=mode) == expected


def test_prompt_text_config_aliases_and_column_name_styles_are_active() -> None:
    result = DataCleaner(
        config={
            "strict": True,
            "auto_types": False,
            "text": {
                "line_break_mode": "single_line",
                "normalize_spaces": True,
                "repair_vietnamese_mojibake": True,
            },
            "column_names": {"style": "upper_snake_case"},
        }
    ).clean(pd.DataFrame({" Tên SP\n": ["  Cà   phê\nsữa  "]}))
    assert result.data.columns.tolist() == ["TEN_SP"]
    assert result.data.loc[0, "TEN_SP"] == "Cà phê sữa"


def test_missing_matching_honours_accent_and_strip_options() -> None:
    assert is_missing("CHUA CO", ["chưa có"], accent_sensitive=False)
    assert not is_missing("CHUA CO", ["chưa có"], accent_sensitive=True)
    assert is_missing(" unknown ", ["unknown"], strip_before_match=True)
    assert not is_missing(" unknown ", ["unknown"], strip_before_match=False)


def test_default_missing_strategy_and_identifier_mean_guard() -> None:
    result = DataCleaner(
        config={
            "auto_types": False,
            "missing": {"default_strategy": "flag_only"},
        }
    ).clean(pd.DataFrame({"note": ["N/A", "ok"]}))
    assert result.data["note_was_missing"].tolist() == [True, False]

    with pytest.raises(ConfigError, match="mã định danh"):
        DataCleaner(config={"missing": {"default_strategy": "fill_mean"}}).clean(
            pd.DataFrame({"order_id": ["001", None]})
        )


def test_explicit_number_locale_ambiguous_dates_and_boolean_vocabulary() -> None:
    numbers = DataCleaner(
        config={
            "auto_types": False,
            "locale": "en_US",
            "columns": {"amount": {"type": "number", "invalid": "keep"}},
        }
    ).clean(pd.DataFrame({"amount": ["1,234.56", "1.234,56", "1 234.56"]}))
    assert numbers.data["amount"].tolist() == [
        Decimal("1234.56"),
        "1.234,56",
        Decimal("1234.56"),
    ]
    assert numbers.report.invalid_by_column == {"amount": 1}

    ambiguous = DataCleaner(
        config={
            "locale": None,
            "type_conversion": {"day_first": None},
            "columns": {"date": {"type": "date", "invalid": "keep"}},
        }
    ).clean(pd.DataFrame({"date": ["03/04/2026"]}))
    assert ambiguous.data.loc[0, "date"] == "03/04/2026"
    assert ambiguous.report.ambiguous_dates_by_column == {"date": 1}

    explicit = DataCleaner(
        config={
            "columns": {
                "date": {"type": "date", "day_first": False, "invalid": "raise"},
                "status": {"type": "boolean", "invalid": "raise"},
            }
        }
    ).clean(pd.DataFrame({"date": ["03/04/2026"], "status": ["inactive"]}))
    assert explicit.data.loc[0, "date"] == pd.Timestamp("2026-03-04")
    assert bool(explicit.data.loc[0, "status"]) is False


def test_duplicate_subset_report_only_most_complete_and_outliers() -> None:
    frame = pd.DataFrame(
        {
            "id": [1, 1, 2, 3, 4],
            "name": [None, "complete", "x", "y", "z"],
            "value": [0, 0, 0, 0, 100],
        }
    )
    report_only = DataCleaner(
        config={
            "auto_types": False,
            "duplicates": {"subset": ["id"], "action": "report_only"},
            "outliers": {
                "enabled": True,
                "columns": ["value"],
                "methods": ["iqr", "zscore"],
                "zscore_threshold": 1.5,
            },
        }
    ).clean(frame)
    assert len(report_only.data) == 5
    assert report_only.report.duplicates_detected_by_subset == 1
    assert report_only.report.outliers_by_column["value"] == {"iqr": 1, "zscore": 1}

    dropped = DataCleaner(
        config={
            "auto_types": False,
            "duplicates": {
                "subset": "id",
                "action": "drop",
                "keep": "most_complete",
            },
        }
    ).clean(frame)
    assert dropped.data.loc[dropped.data["id"].eq(1), "name"].item() == "complete"


@pytest.mark.parametrize(
    ("profile", "frame", "expected_rule"),
    [
        (
            "fnb",
            pd.DataFrame(
                {
                    "order_id": ["A", "B"],
                    "quantity": [2, -1],
                    "unit_price": [10, 10],
                    "discount": [0, 0],
                    "tax": [0, 0],
                    "total": [20, 99],
                }
            ),
            "fnb.total_mismatch",
        ),
        (
            "finance",
            pd.DataFrame(
                {
                    "transaction_id": ["T1", "T1"],
                    "debit": [10, 5],
                    "credit": [0, 2],
                    "amount": [10, 3],
                }
            ),
            "finance.transaction_id_duplicate",
        ),
        (
            "ecommerce",
            pd.DataFrame(
                {
                    "order_id": ["O1"],
                    "sku": ["S1"],
                    "quantity": [2],
                    "unit_price": [10],
                    "discount": [1],
                    "shipping_fee": [2],
                    "order_total": [99],
                }
            ),
            "ecommerce.order_total_mismatch",
        ),
        (
            "marketing",
            pd.DataFrame(
                {
                    "campaign_id": ["C1"],
                    "spend": [100],
                    "impressions": [10],
                    "clicks": [20],
                    "ctr": [Decimal("0.1")],
                }
            ),
            "marketing.clicks_exceed_impressions",
        ),
    ],
)
def test_builtin_profiles_execute_cross_column_rules(
    profile: str, frame: pd.DataFrame, expected_rule: str
) -> None:
    result = DataCleaner(profile=profile).clean(frame)
    assert result.report.domain_rule_violations[expected_rule] > 0
    assert result.report.validation_failed > 0


def test_domain_and_public_transforms_are_report_only_pipe_friendly_and_copying() -> None:
    source = pd.DataFrame(
        {
            " Tên SP ": ["  Cà   phê ", "N/A"],
            "id": [1, 1],
            "extra": [None, "full"],
            "more": [None, "yes"],
        }
    )
    output = (
        source.pipe(normalize_column_names)
        .pipe(normalize_text, columns=["ten_sp"], whitespace_mode="single_line")
        .pipe(replace_missing, columns=["ten_sp"])
        .pipe(deduplicate, subset=["id"], keep="most_complete")
    )
    assert source.columns.tolist() == [" Tên SP ", "id", "extra", "more"]
    assert source.iloc[0, 0] == "  Cà   phê "
    assert output["extra"].item() == "full"

    business = pd.DataFrame({"impressions": [1], "clicks": [2]})
    snapshot = business.copy(deep=True)
    domain = validate_domain_rules(business, "marketing")
    assert domain.violations == {"marketing.clicks_exceed_impressions": 1}
    pd.testing.assert_frame_equal(business, snapshot)


def test_prompt_named_transformations_compose_with_dataframe_pipe() -> None:
    source = pd.DataFrame(
        {
            " Số tiền ": ["1.234,50", "2.000,00"],
            " Ghi chú ": ["  Tiáº¿ng\r\nViá»‡t ", " N/A "],
            "id": [1, 1],
        }
    )
    output = (
        source.pipe(clean_names)
        .pipe(normalize_unicode_frame)
        .pipe(repair_vietnamese_text, columns=["so_tien", "ghi_chu"])
        .pipe(normalize_whitespace_frame, mode="single_line")
        .pipe(standardize_missing)
        .pipe(coerce_types, schema={"so_tien": "number"})
        .pipe(flag_duplicates, subset=["id"])
        .pipe(
            validate_schema,
            schema={
                "so_tien": {"type": "number", "min": 0},
                "ghi_chu": {"type": "text"},
                "id": {"type": "identifier", "required": True},
                "is_duplicate": {"type": "boolean"},
            },
        )
    )
    assert source.columns.tolist() == [" Số tiền ", " Ghi chú ", "id"]
    assert output["so_tien"].tolist() == [Decimal("1234.50"), Decimal("2000.00")]
    assert output.loc[0, "ghi_chu"] == "Tiếng Việt"
    assert pd.isna(output.loc[1, "ghi_chu"])
    assert output["is_duplicate"].tolist() == [True, True]

    with pytest.raises(SchemaValidationError, match="không đạt"):
        validate_schema(
            pd.DataFrame({"amount": [-1]}),
            schema={"amount": {"type": "number", "min": 0}},
        )
