import json

import pandas as pd
import pytest

import dataclean
import vietclean.api as api_module
from vietclean.api import clean_file, explain_report, profile_file, validate_file
from vietclean.exceptions import UnsafeInputError
from vietclean.io import read_data, write_data
from vietclean.validation import validate_dataframe


def test_dataclean_compatibility_api_matches_prompt_example():
    assert dataclean.clean_file is clean_file
    assert dataclean.__version__ == "0.1.0"


def test_clean_file_creates_complete_default_bundle_without_touching_source(tmp_path):
    source = tmp_path / "orders.csv"
    source.write_text(
        "id,note\n1,  xin\\tchào  \n2,=2+2\n",
        encoding="utf-8",
    )
    original = source.read_bytes()

    result = clean_file(source)

    assert source.read_bytes() == original
    assert result.output_path == tmp_path / "orders_output" / "orders_cleaned.csv"
    expected = {
        result.output_path,
        result.audit_path,
        result.quality_json_path,
        result.quality_html_path,
        result.rejects_path,
        result.column_mapping_path,
        result.run_summary_path,
    }
    assert all(path is not None and path.exists() for path in expected)
    audit = json.loads(result.audit_path.read_text(encoding="utf-8"))
    assert audit["status"] == "success"
    assert audit["finished_at"]
    assert audit["input_sha256"]
    assert audit["output_sha256"]
    assert audit["formula_cells_sanitized"] == 1
    assert audit["run_id"] == result.run_id
    cleaned = pd.read_csv(result.output_path, dtype=str)
    assert cleaned.loc[1, "note"] == "'=2+2"


def test_validate_dataframe_aggregates_all_issues_without_mutating_input():
    frame = pd.DataFrame({"amount": [10, -1], "extra": ["a", "b"]})
    before = frame.copy(deep=True)
    schema = {
        "required_columns": ["amount", "order_id"],
        "allow_extra_columns": False,
        "columns": {"amount": {"type": "number", "min": 0}},
    }

    result = validate_dataframe(frame, schema)

    assert not result.valid
    assert result.checks_failed >= 3
    assert {issue.code for issue in result.issues} >= {
        "VC-VALIDATE-002",
        "VC-VALIDATE-003",
        "VC-VALIDATE-004",
    }
    pd.testing.assert_frame_equal(frame, before)
    serialized = json.dumps(result.to_dict(), ensure_ascii=False)
    assert '"a"' not in serialized and '"b"' not in serialized


def test_profile_validate_and_explain_file_helpers(tmp_path):
    source = tmp_path / "data.csv"
    source.write_text("id,amount\n1,10\n2,-2\n", encoding="utf-8")
    schema = tmp_path / "schema.json"
    schema.write_text(
        json.dumps({"columns": {"amount": {"type": "number", "min": 0}}}),
        encoding="utf-8",
    )

    profile = profile_file(source)
    validation = validate_file(source, schema)
    explanation = explain_report(
        {
            "score": 80,
            "components": {
                "validity": {
                    "score": 60,
                    "deduction": {"reason": "aggregate failures"},
                }
            },
        }
    )

    assert profile["rows"] == 2
    assert validation.valid is False
    assert "Data Quality Score: 80/100" in explanation
    assert "aggregate failures" in explanation


def test_clean_file_enforces_output_root_for_entire_bundle(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("id\n1\n", encoding="utf-8")
    safe_root = tmp_path / "safe"

    result = clean_file(
        source,
        output_dir=safe_root / "run",
        output_root=safe_root,
    )

    assert result.output_path.is_relative_to(safe_root)
    assert all(
        path.is_relative_to(safe_root)
        for path in (
            result.audit_path,
            result.quality_json_path,
            result.rejects_path,
            result.column_mapping_path,
            result.run_summary_path,
        )
    )
    with pytest.raises(UnsafeInputError, match="output_root"):
        clean_file(
            source,
            output_dir=safe_root / ".." / "escaped",
            output_root=safe_root,
        )


def test_clean_file_supports_offline_sqlite_round_trip(tmp_path):
    source = tmp_path / "source.db"
    output = tmp_path / "cleaned.db"
    write_data(pd.DataFrame({"id": ["001"], "note": ["  sạch  "]}), source, table="orders")

    result = clean_file(source, output_path=output, table="orders")

    assert result.output_path == output
    cleaned = read_data(output, table="orders_clean")
    assert cleaned.loc[0, "id"] == "001"
    assert cleaned.loc[0, "note"] == "sạch"


def test_clean_file_rejects_unsafe_or_ambiguous_destinations(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("id\n1\n", encoding="utf-8")

    with pytest.raises(TypeError, match="overwrite"):
        clean_file(source, overwrite=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="secure_mode"):
        clean_file(source, secure_mode=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="output_path"):
        clean_file("postgresql://reader:secret@db/sales")
    with pytest.raises(ValueError, match="remote output"):
        clean_file(source, output_path="postgresql://writer:secret@db/sales")
    with pytest.raises(ValueError, match="ghi đè input"):
        clean_file(source, output_path=source)
    with pytest.raises(ValueError, match="đường dẫn khác nhau"):
        clean_file(
            source,
            output_path=tmp_path / "bundle" / "audit_log.json",
            output_dir=tmp_path / "bundle",
        )


def test_clean_file_failure_audit_redacts_credentials(tmp_path, monkeypatch):
    source = tmp_path / "source.csv"
    source.write_text("id\n1\n", encoding="utf-8")

    def fail_read(*_args, **_kwargs):
        raise RuntimeError(
            "driver failed at postgresql://alice:super-secret@db.internal/sales?token=x"
        )

    monkeypatch.setattr(api_module, "read_data", fail_read)
    with pytest.raises(RuntimeError, match="driver failed"):
        clean_file(source)

    audit = json.loads(
        (tmp_path / "source_output" / "audit_log.json").read_text(encoding="utf-8")
    )
    assert audit["status"] == "failed"
    assert audit["error_code"] == "VC-PROCESS-999"
    assert "super-secret" not in audit["error_message"]
    assert "token=x" not in audit["error_message"]
    assert "postgresql://***@db.internal/sales" in audit["error_message"]


def test_clean_file_refuses_existing_bundle_and_explain_handles_audit(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("id\n1\n", encoding="utf-8")
    first = clean_file(source)

    with pytest.raises(FileExistsError, match="Artifact"):
        clean_file(source)
    explanation = explain_report(first.audit_path)
    assert "VietClean run summary" in explanation
    assert first.run_id in explanation
    list_report = tmp_path / "list.json"
    list_report.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        explain_report(list_report)
