import json

import pytest

from benchmarks.benchmark import DEFAULT_ROWS, run_case
from tools.check_core_coverage import CORE_MODULES, core_coverage


@pytest.mark.parametrize("case", sorted(DEFAULT_ROWS))
def test_benchmark_workloads_have_small_deterministic_smoke_mode(case: str) -> None:
    result = run_case(case, rows=20)

    assert result["case"] == case
    assert result["configured_rows"] == 20
    assert result["rows_processed"] == 20
    assert float(result["seconds"]) >= 0
    assert json.loads(json.dumps(result))["case"] == case


def test_benchmark_rejects_unknown_or_ambiguous_size() -> None:
    with pytest.raises(ValueError, match="không được hỗ trợ"):
        run_case("unknown", 1)
    with pytest.raises(ValueError, match="số nguyên dương"):
        run_case("csv-1m", True)


def test_core_coverage_aggregates_configured_modules_and_reports_missing() -> None:
    payload = {
        "files": {
            name.replace("/", "\\"): {
                "summary": {"covered_lines": 9, "num_statements": 10}
            }
            for name in CORE_MODULES
        }
    }
    percent, missing = core_coverage(payload)
    assert percent == 90.0
    assert missing == []

    payload["files"].pop(next(iter(payload["files"])))
    percent, missing = core_coverage(payload)
    assert percent == 90.0
    assert len(missing) == 1
