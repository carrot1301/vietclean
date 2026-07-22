import json

import pandas as pd
import pytest

from vietclean.quality import (
    COMPONENT_ORDER,
    build_quality_report,
    write_quality_report,
)
from vietclean.report import CleaningReport


def _audit_for(before: pd.DataFrame, after: pd.DataFrame, **updates: object) -> CleaningReport:
    report = CleaningReport(
        profile="generic",
        rows_before=len(before),
        rows_after=len(after),
        columns_before=len(before.columns),
        columns_after=len(after.columns),
    )
    for name, value in updates.items():
        setattr(report, name, value)
    return report


def test_quality_score_is_bounded_and_matches_published_formula() -> None:
    before = pd.DataFrame(
        {"id": [1, 1, 2], "email": ["a@example.com", "a@example.com", "bad"]}
    )
    after = pd.DataFrame(
        {
            "id": [1, 1, 2],
            "email": ["a@example.com", "a@example.com", pd.NA],
        }
    )
    audit = _audit_for(before, after, invalid_by_column={"email": 1})

    report = build_quality_report(before, after, audit)

    assert 0 <= report["score"] <= 100
    weights = report["formula"]["weights"]
    assert sum(weights.values()) == pytest.approx(1.0)
    expected = sum(
        report["components"][name]["score"] * weights[name]
        for name in COMPONENT_ORDER
    )
    assert report["score"] == pytest.approx(round(expected, 2))
    for name in COMPONENT_ORDER:
        component = report["components"][name]
        assert 0 <= component["score"] <= 100
        assert component["formula"]
        assert component["deduction"]["reason"]
        assert component["deduction"]["count"] >= 0

    assert report["components"]["completeness"]["score"] == pytest.approx(83.33)
    assert report["components"]["validity"]["score"] == pytest.approx(83.33)
    assert report["components"]["uniqueness"]["score"] == pytest.approx(66.67)
    assert report["components"]["consistency"]["score"] == 100
    assert report["components"]["integrity"]["score"] == 100


def test_perfect_aggregate_data_scores_one_hundred() -> None:
    frame = pd.DataFrame({"id": [1, 2], "status": ["new", "done"]})

    report = build_quality_report(frame, frame.copy(), _audit_for(frame, frame))

    assert report["score"] == 100
    assert all(report["components"][name]["score"] == 100 for name in COMPONENT_ORDER)


def test_report_contains_no_raw_values_samples_or_warning_text() -> None:
    secrets = [
        "alice.secret@example.com",
        "+84912345678",
        "ACCT-001-VERY-PRIVATE",
        "12 Sensitive Street",
    ]
    before = pd.DataFrame(
        {
            "customer_email": [secrets[0]],
            "phone": [secrets[1]],
            "account": [secrets[2]],
            "address": [secrets[3]],
        }
    )
    audit = _audit_for(
        before,
        before,
        invalid_by_column={"customer_email": 1},
        warnings=[f"Invalid private value: {secrets[0]}"],
    )

    report = build_quality_report(before, before.copy(), audit, profile="finance")
    serialized = json.dumps(report, ensure_ascii=False, allow_nan=False)

    assert all(secret not in serialized for secret in secrets)
    assert "Invalid private value" not in serialized
    assert "customer_email" not in serialized
    assert report["privacy"] == {
        "contains_raw_values": False,
        "contains_samples": False,
        "contains_warning_text": False,
        "note": "Aggregate counts and scores only; no cell values or value samples are included.",
    }
    assert report["summary"]["warning_count"] == 1
    assert report["summary"]["invalid_detections"] == 1


def test_integrity_reconciles_recorded_removals_without_penalty() -> None:
    before = pd.DataFrame({"id": [1, 1, 2], "empty": [pd.NA, pd.NA, pd.NA]})
    after = pd.DataFrame({"id": [1, 2]})
    audit = _audit_for(
        before,
        after,
        duplicates_removed=1,
        empty_columns_removed=["empty"],
    )

    report = build_quality_report(before, after, audit)

    integrity = report["components"]["integrity"]
    assert integrity["score"] == 100
    assert integrity["metrics"]["unreconciled_row_units"] == 0
    assert integrity["metrics"]["unreconciled_column_units"] == 0


def test_custom_profile_weights_are_normalized_and_json_safe() -> None:
    frame = pd.DataFrame({"value": [1, 2]})
    profile = {
        "name": "custom",
        "quality": {
            "weights": {
                "completeness": 4,
                "validity": 3,
                "uniqueness": 2,
                "consistency": 1,
                "integrity": 0,
            }
        },
    }

    report = build_quality_report(frame, frame, _audit_for(frame, frame), profile=profile)

    assert report["formula"]["weights"] == {
        "completeness": 0.4,
        "validity": 0.3,
        "uniqueness": 0.2,
        "consistency": 0.1,
        "integrity": 0.0,
    }
    json.dumps(report, allow_nan=False)


def test_html_is_deterministic_self_contained_and_escapes_all_dynamic_text(tmp_path) -> None:
    frame = pd.DataFrame({"value": [1]})
    malicious_profile = '<script>alert("profile")</script>&'
    report = build_quality_report(
        frame,
        frame,
        _audit_for(frame, frame),
        profile=malicious_profile,
    )
    report["components"]["validity"]["deduction"]["reason"] = (
        '"><img src=x onerror="alert(1)">'
    )
    first_json = tmp_path / "first.json"
    first_html = tmp_path / "first.html"
    second_json = tmp_path / "second.json"
    second_html = tmp_path / "second.html"

    write_quality_report(report, first_json, first_html)
    write_quality_report(report, second_json, second_html)

    html = first_html.read_text(encoding="utf-8")
    assert html == second_html.read_text(encoding="utf-8")
    assert json.loads(first_json.read_text(encoding="utf-8")) == report
    assert first_json.read_text(encoding="utf-8") == second_json.read_text(encoding="utf-8")
    assert "<script>alert" not in html
    assert "<img src=x" not in html
    assert '&lt;script&gt;alert(&quot;' in html
    assert '&lt;img src=x onerror=&quot;' in html
    assert "http://" not in html and "https://" not in html
    assert not list(tmp_path.glob(".*.tmp"))


def test_writer_rejects_same_destination_and_non_finite_json(tmp_path) -> None:
    destination = tmp_path / "report.out"
    with pytest.raises(ValueError, match="different"):
        write_quality_report({"score": 100}, destination, destination)
    with pytest.raises(ValueError, match="JSON-safe"):
        write_quality_report({"score": float("nan")}, tmp_path / "bad.json")
