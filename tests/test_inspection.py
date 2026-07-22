import pandas as pd
import pytest

from vietclean.inspection import inspect_dataframe


def test_inspection_reports_quality_without_exposing_samples_by_default():
    frame = pd.DataFrame(
        {
            "email": [" a@example.com ", None, "broken"],
            "ghi chú": ["hai\ndòng", "Tráº§n", "ok"],
            "empty": [None, None, None],
        }
    )

    result = inspect_dataframe(frame, profile="marketing")

    assert result["rows"] == 3
    assert result["completely_empty_columns"] == ["empty"]
    email = next(item for item in result["column_details"] if item["name"] == "email")
    assert email["semantic_type"] == "email"
    assert email["missing"] == 1
    assert email["leading_or_trailing_space"] == 1
    assert "samples" not in email


def test_inspection_samples_are_explicit_opt_in():
    result = inspect_dataframe(pd.DataFrame({"x": [1, 2, 2]}), include_samples=True)
    assert result["column_details"][0]["samples"] == [1, 2]


def test_inspection_profiles_numeric_text_pii_and_formula_risk_without_raw_values():
    frame = pd.DataFrame(
        {
            "số điện thoại": ["0901234567", "=HYPERLINK('x')"],
            "amount": [10, 20],
        }
    )

    result = inspect_dataframe(frame, profile="finance")
    phone = result["column_details"][0]
    amount = result["column_details"][1]

    assert phone["possible_pii"] == "phone"
    assert phone["formula_injection_risk"] == 1
    assert amount["numeric"] == {
        "min": 10,
        "max": 20,
        "median": 15,
        "iqr_outliers": 0,
    }
    assert "0901234567" not in str(result)


def test_inspection_caps_unique_tracking_and_marks_lower_bound():
    result = inspect_dataframe(
        pd.DataFrame({"id": ["001", "002", "003", "004"]}),
        max_unique_values=3,
    )

    details = result["column_details"][0]
    assert details["unique"] == 3
    assert details["unique_truncated"] is True
    assert details["high_cardinality"] is False  # fewer than 100 rows


def test_inspection_validates_bounds_and_profiles_dates_controls_and_unhashables():
    with pytest.raises(ValueError, match="sample_size"):
        inspect_dataframe(pd.DataFrame({"x": [1]}), sample_size=101)
    with pytest.raises(ValueError, match="max_unique"):
        inspect_dataframe(pd.DataFrame({"x": [1]}), max_unique_values=0)

    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "text": ["  a  b\n�\x01", "ok"],
            "objects": [[1], [2]],
        }
    )
    result = inspect_dataframe(frame, include_samples=True, sample_size=1)
    date, text, objects = result["column_details"]

    assert date["date"] == {
        "min": "2026-01-01T00:00:00",
        "max": "2026-01-02T00:00:00",
    }
    assert text["leading_or_trailing_space"] == 1
    assert text["repeated_whitespace"] == 1
    assert text["replacement_character"] == 1
    assert text["unexpected_control_character"] == 1
    assert objects["unique_approximate"] is True
    assert objects["samples"] == ["[1]"]
    assert result["duplicate_rows_approximate"] is True
