import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import vietclean.cli as cli_module
from vietclean.cli import (
    _default_output,
    _default_report,
    _display_location,
    _guard_local_output,
    _header_row,
    _sheet,
    main,
)
from vietclean.exceptions import UnsafeInputError


def _write_csv(path: Path) -> None:
    path.write_text(
        "email,số điện thoại,ghi chú\n"
        ' TEST@EXAMPLE.COM ,"090 123 4567","  hai\\tdòng  "\n'
        'N/A,"0912 000 111",--\n',
        encoding="utf-8",
    )


def test_console_is_forced_to_utf8_without_assuming_a_windows_code_page(monkeypatch):
    class RecordingStream:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        def reconfigure(self, **options: str) -> None:
            self.calls.append(options)

    stdout = RecordingStream()
    stderr = RecordingStream()
    monkeypatch.setattr(cli_module, "sys", SimpleNamespace(stdout=stdout, stderr=stderr))

    cli_module._configure_console()

    expected = [{"encoding": "utf-8", "errors": "replace"}]
    assert stdout.calls == expected
    assert stderr.calls == expected


def test_cli_clean_writes_data_and_report(tmp_path, capsys):
    source = tmp_path / "dirty.csv"
    output = tmp_path / "clean.csv"
    report = tmp_path / "report.json"
    quality_json = tmp_path / "quality.json"
    quality_html = tmp_path / "quality.html"
    _write_csv(source)

    code = main(
        [
            "clean",
            str(source),
            "-o",
            str(output),
            "--profile",
            "marketing",
            "--report",
            str(report),
            "--quality-report",
            str(quality_json),
            "--quality-html",
            str(quality_html),
        ]
    )

    assert code == 0
    cleaned = pd.read_csv(output, dtype=str)
    assert cleaned.loc[0, "email"] == "TEST@example.com"
    assert cleaned.loc[0, "số điện thoại"] == "'+84901234567"
    audit = json.loads(report.read_text(encoding="utf-8"))
    assert audit["profile"] == "marketing"
    assert audit["cells_changed"] >= 3
    quality = json.loads(quality_json.read_text(encoding="utf-8"))
    assert 0 <= quality["score"] <= 100
    assert "Data Quality Score" in quality_html.read_text(encoding="utf-8")
    assert f"Quality HTML: {quality_html}" in capsys.readouterr().out


def test_cli_dry_run_only_writes_report(tmp_path):
    source = tmp_path / "dirty.csv"
    output = tmp_path / "must-not-exist.csv"
    report = tmp_path / "dry.json"
    _write_csv(source)

    code = main(
        [
            "clean",
            str(source),
            "-o",
            str(output),
            "--dry-run",
            "--report",
            str(report),
        ]
    )

    assert code == 0
    assert not output.exists()
    assert report.exists()


def test_cli_refuses_to_overwrite_existing_file(tmp_path):
    source = tmp_path / "dirty.csv"
    output = tmp_path / "existing.csv"
    _write_csv(source)
    output.write_text("keep me", encoding="utf-8")

    code = main(["clean", str(source), "-o", str(output), "--no-report"])

    assert code == 3
    assert output.read_text(encoding="utf-8") == "keep me"


def test_cli_init_config_and_inspect_json(tmp_path):
    config = tmp_path / "rules.json"
    assert main(["init-config", str(config), "--profile", "fnb"]) == 0
    assert json.loads(config.read_text(encoding="utf-8"))["profile"] == "fnb"

    source = tmp_path / "dirty.csv"
    inspection = tmp_path / "inspection.json"
    _write_csv(source)
    assert main(["inspect", str(source), "-o", str(inspection)]) == 0
    result = json.loads(inspection.read_text(encoding="utf-8"))
    assert result["rows"] == 2
    assert "samples" not in result["column_details"][0]


def test_cli_accepts_dataclean_style_profile_and_preset_aliases(tmp_path):
    source = tmp_path / "dirty.csv"
    inspection = tmp_path / "inspection.json"
    output = tmp_path / "clean.csv"
    _write_csv(source)

    assert main(["profile", str(source), "--preset", "fnb", "-o", str(inspection)]) == 0
    assert main(
        [
            "clean",
            str(source),
            "--preset",
            "fnb",
            "-o",
            str(output),
            "--no-report",
            "--no-quality-report",
            "--no-rejects",
        ]
    ) == 0

    assert json.loads(inspection.read_text(encoding="utf-8"))["source"]["profile"] == "fnb"
    assert output.exists()


def test_uri_defaults_never_turn_database_credentials_into_a_local_path():
    uri = "postgresql://user:secret@db.internal/sales"

    assert _default_output(uri) is None
    assert _default_report(uri, uri) == "vietclean.cleaning-report.json"
    assert _default_report(uri, "input.csv") == "input.cleaning-report.json"
    assert _display_location(uri + "?token=private") == (
        "postgresql://***@db.internal/sales"
    )


def test_database_source_and_output_cannot_be_the_same_endpoint(tmp_path):
    with pytest.raises(UnsafeInputError):
        _guard_local_output(
            "postgresql+psycopg://writer:new@db.internal/sales",
            "postgresql://reader:old@DB.INTERNAL/sales",
            overwrite=True,
        )

    database = tmp_path / "source.db"
    database.touch()
    with pytest.raises(UnsafeInputError):
        _guard_local_output(
            database.resolve().as_uri().replace("file://", "sqlite://"),
            str(database),
            overwrite=True,
        )


def test_cli_captures_bad_rows_sanitizes_formulas_and_audits_quality(tmp_path):
    source = tmp_path / "dirty.csv"
    output = tmp_path / "clean.csv"
    audit = tmp_path / "audit.json"
    quality = tmp_path / "quality.json"
    html = tmp_path / "quality.html"
    rejects = tmp_path / "rejects.csv"
    source.write_text("id,note\n1,=2+2\n2,ok,extra\n", encoding="utf-8")

    code = main(
        [
            "clean",
            str(source),
            "-o",
            str(output),
            "--report",
            str(audit),
            "--quality-report",
            str(quality),
            "--quality-html",
            str(html),
            "--rejects",
            str(rejects),
        ]
    )

    assert code == 0
    assert pd.read_csv(output, dtype=str).loc[0, "note"] == "'=2+2"
    audit_data = json.loads(audit.read_text(encoding="utf-8"))
    quality_data = json.loads(quality.read_text(encoding="utf-8"))
    assert audit_data["formula_cells_sanitized"] == 1
    assert audit_data["rejected_rows"] == 1
    assert audit_data["quality_score"] == quality_data["score"]
    assert len(pd.read_csv(rejects)) == 1
    assert html.exists()


def test_cli_overwrite_never_allows_destroying_input_but_replaces_other_output(tmp_path):
    source = tmp_path / "source.csv"
    output = tmp_path / "output.csv"
    _write_csv(source)
    original = source.read_bytes()

    assert main(["clean", str(source), "-o", str(source), "--overwrite"]) == 3
    assert source.read_bytes() == original

    output.write_text("old", encoding="utf-8")
    assert (
        main(
            [
                "clean",
                str(source),
                "-o",
                str(output),
                "--overwrite",
                "--no-report",
                "--no-quality-report",
                "--no-rejects",
            ]
        )
        == 0
    )
    assert "email" in output.read_text(encoding="utf-8-sig")


def test_cli_default_clean_creates_named_complete_bundle(tmp_path):
    source = tmp_path / "messy_sales.csv"
    _write_csv(source)

    code = main(["clean", str(source), "--preset", "fnb", "--quiet"])

    assert code == 0
    bundle = tmp_path / "messy_sales_output"
    assert {path.name for path in bundle.iterdir()} >= {
        "messy_sales_cleaned.csv",
        "audit_log.json",
        "quality_report.json",
        "quality_report.html",
        "rejected_rows.csv",
        "column_mapping.json",
        "run_summary.txt",
    }
    audit = json.loads((bundle / "audit_log.json").read_text(encoding="utf-8"))
    assert audit["status"] == "success"
    assert audit["finished_at"]
    assert audit["artifact_sha256"]["data"]


def test_cli_quality_threshold_writes_artifacts_then_returns_one(tmp_path):
    source = tmp_path / "incomplete.csv"
    source.write_text("id,note\n1,\n2,\n", encoding="utf-8")

    code = main(
        [
            "clean",
            str(source),
            "--quality-threshold",
            "100",
            "--quiet",
        ]
    )

    assert code == 1
    bundle = tmp_path / "incomplete_output"
    assert (bundle / "incomplete_cleaned.csv").exists()
    assert (bundle / "audit_log.json").exists()
    assert json.loads((bundle / "quality_report.json").read_text(encoding="utf-8"))[
        "score"
    ] < 100


def test_cli_validate_and_explain_commands(tmp_path, capsys):
    source = tmp_path / "values.csv"
    source.write_text("amount\n10\n-2\n", encoding="utf-8")
    schema = tmp_path / "schema.json"
    schema.write_text(
        json.dumps({"columns": {"amount": {"type": "number", "min": 0}}}),
        encoding="utf-8",
    )
    validation = tmp_path / "validation.json"

    assert main(["validate", str(source), "--schema", str(schema), "-o", str(validation)]) == 1
    assert json.loads(validation.read_text(encoding="utf-8"))["valid"] is False

    quality = tmp_path / "quality.json"
    quality.write_text(
        json.dumps(
            {
                "score": 75,
                "components": {
                    "validity": {
                        "score": 50,
                        "deduction": {"reason": "validation failures"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert main(["explain", str(quality)]) == 0
    output = capsys.readouterr().out
    assert "Data Quality Score: 75/100" in output
    assert "validation failures" in output


def test_cli_json_logging_uses_correlation_id(tmp_path):
    source = tmp_path / "data.csv"
    output = tmp_path / "clean.csv"
    log = tmp_path / "run.jsonl"
    _write_csv(source)

    assert main(
        [
            "clean",
            str(source),
            "-o",
            str(output),
            "--no-report",
            "--no-quality-report",
            "--no-rejects",
            "--no-column-mapping",
            "--no-run-summary",
            "--log-file",
            str(log),
            "--log-format",
            "json",
            "--run-id",
            "daily-job-01",
            "--quiet",
        ]
    ) == 0
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [record["run_id"] for record in records] == ["daily-job-01"] * 2
    assert [record["level"] for record in records] == ["INFO", "INFO"]


def test_cli_cleans_all_excel_sheets_to_one_atomic_workbook(tmp_path):
    pytest.importorskip("openpyxl")
    source = tmp_path / "workbook.xlsx"
    with pd.ExcelWriter(source, engine="openpyxl") as writer:
        pd.DataFrame({"id": ["001"], "note": ["  một  "]}).to_excel(
            writer, sheet_name="Đơn hàng", index=False
        )
        pd.DataFrame({"id": ["002"], "note": [" =2+2"]}).to_excel(
            writer, sheet_name="Chi tiết", index=False
        )

    assert main(["clean", str(source), "--all-sheets", "--quiet"]) == 0

    bundle = tmp_path / "workbook_output"
    output = bundle / "workbook_cleaned.xlsx"
    sheets = pd.read_excel(output, sheet_name=None, dtype=str)
    assert list(sheets) == ["Đơn hàng", "Chi tiết"]
    assert sheets["Đơn hàng"].loc[0, "note"] == "một"
    assert sheets["Chi tiết"].loc[0, "note"] == "'=2+2"
    audit = json.loads((bundle / "audit_log.json").read_text(encoding="utf-8"))
    assert audit["source_sheet_count"] == 2
    assert set(audit["sheet_reports"]) == {"Đơn hàng", "Chi tiết"}
    assert audit["formula_cells_sanitized"] == 1


def test_cli_chunk_mode_streams_csv_and_audits_checkpoints(tmp_path):
    source = tmp_path / "large.csv"
    pd.DataFrame(
        {"id": [f"{index:03}" for index in range(5)], "note": ["  x  "] * 5}
    ).to_csv(source, index=False)

    assert main(["clean", str(source), "--chunksize", "2", "--quiet"]) == 0

    bundle = tmp_path / "large_output"
    cleaned = pd.read_csv(bundle / "large_cleaned.csv", dtype=str)
    assert cleaned["id"].tolist() == ["000", "001", "002", "003", "004"]
    assert cleaned["note"].tolist() == ["x"] * 5
    audit = json.loads((bundle / "audit_log.json").read_text(encoding="utf-8"))
    quality = json.loads((bundle / "quality_report.json").read_text(encoding="utf-8"))
    assert audit["streaming_mode"] is True
    assert audit["chunks_processed"] == 3
    assert audit["rows_before"] == 5
    assert audit["rows_after"] == 5
    assert quality["aggregation"]["partition"] == "chunk"


def test_cli_argument_converters_cover_named_sheets_and_header_modes():
    assert _sheet("2") == 2
    assert _sheet("Dữ liệu") == "Dữ liệu"
    assert _header_row("infer") == "infer"
    assert _header_row("NONE") is None
    assert _header_row("3") == 3
    with pytest.raises(argparse.ArgumentTypeError, match="không được âm"):
        _header_row("-1")
    with pytest.raises(argparse.ArgumentTypeError, match="infer"):
        _header_row("header")


def test_cli_config_lifecycle_and_successful_validation(tmp_path, capsys):
    config = tmp_path / "cleaning.toml"
    assert main(["config", "init", str(config), "--profile", "finance"]) == 0
    assert main(["config", "validate", str(config)]) == 0
    assert "Config hợp lệ" in capsys.readouterr().out
    assert main(["config", "init", str(config)]) == 3
    assert main(["init-config", str(tmp_path / "bad.toml"), "--profile", "missing"]) == 2

    source = tmp_path / "valid.csv"
    source.write_text("amount\n10\n", encoding="utf-8")
    schema = tmp_path / "schema.json"
    schema.write_text(
        json.dumps({"columns": {"amount": {"type": "number", "min": 0}}}),
        encoding="utf-8",
    )
    assert main(["validate", str(source), "--schema", str(schema)]) == 0


def test_cli_chunk_dry_run_and_invalid_streaming_options(tmp_path):
    source = tmp_path / "data.csv"
    source.write_text("a,b\n1,\n2,value\n", encoding="utf-8")
    output = tmp_path / "dry.csv"
    audit = tmp_path / "dry-audit.json"

    assert main(
        [
            "clean",
            str(source),
            "--chunksize",
            "1",
            "--dry-run",
            "-o",
            str(output),
            "--report",
            str(audit),
            "--quiet",
        ]
    ) == 0
    assert not output.exists()
    assert json.loads(audit.read_text(encoding="utf-8"))["chunks_processed"] == 2
    assert main(["clean", str(source), "--chunksize", "0", "--quiet"]) == 2
    assert main(
        ["clean", str(source), "--chunksize", "1", "-o", str(tmp_path / "bad.xlsx")]
    ) == 4


def test_chunk_schema_change_fails_atomically_with_failure_audit(tmp_path):
    source = tmp_path / "variable.csv"
    source.write_text("a,b\n1,\n2,present\n", encoding="utf-8")
    config = tmp_path / "drop.json"
    config.write_text(json.dumps({"drop": {"empty_columns": True}}), encoding="utf-8")

    code = main(
        [
            "clean",
            str(source),
            "--chunksize",
            "1",
            "--config",
            str(config),
            "--quiet",
        ]
    )

    bundle = tmp_path / "variable_output"
    assert code == 1
    assert not (bundle / "variable_cleaned.csv").exists()
    audit = json.loads((bundle / "audit_log.json").read_text(encoding="utf-8"))
    assert audit["status"] == "failed"
    assert audit["error_code"] == "VC-VALIDATE-001"


def test_multi_sheet_audit_warns_about_formulas_and_merged_ranges(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    source = tmp_path / "features.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(["id", "note"])
    sheet.append([1, "text"])
    sheet["D2"] = "=1+1"
    sheet.merge_cells("A4:B4")
    sheet["A4"] = "merged"
    workbook.save(source)
    workbook.close()

    assert main(["clean", str(source), "--all-sheets", "--quiet"]) == 0

    audit = json.loads(
        (tmp_path / "features_output" / "audit_log.json").read_text(encoding="utf-8")
    )
    assert any("formula cell" in warning for warning in audit["warnings"])
    assert any("merged ranges" in warning for warning in audit["warnings"])


def test_cli_rejects_invalid_logging_run_id_as_configuration_error(tmp_path):
    source = tmp_path / "data.csv"
    source.write_text("id\n1\n", encoding="utf-8")

    assert main(["clean", str(source), "--run-id", "contains a space"]) == 2
