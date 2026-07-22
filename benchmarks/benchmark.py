"""Small deterministic benchmarks for VietClean; never run automatically in CI."""

from __future__ import annotations

import argparse
import csv
import gc
import json
from pathlib import Path
import tempfile
from time import perf_counter
import tracemalloc
from typing import Callable

import pandas as pd

from vietclean import DataCleaner
from vietclean.io import read_chunks


DEFAULT_ROWS = {
    "dataframe-100k": 100_000,
    "csv-1m": 1_000_000,
    "vietnamese-text": 100_000,
    "finance-numeric": 100_000,
}


def _measure(name: str, rows: int, operation: Callable[[], int]) -> dict[str, float | int | str]:
    gc.collect()
    tracemalloc.start()
    started = perf_counter()
    rows_processed = operation()
    elapsed = perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "case": name,
        "configured_rows": rows,
        "rows_processed": rows_processed,
        "seconds": round(elapsed, 6),
        "rows_per_second": round(rows_processed / elapsed, 2) if elapsed else 0.0,
        "python_peak_memory_mb": round(peak / (1024 * 1024), 2),
    }


def benchmark_dataframe(rows: int) -> int:
    frame = pd.DataFrame(
        {
            "Mã": [f"ID-{index:07d}" for index in range(rows)],
            "Ghi chú": ["  Cà   phê sữa  " if index % 5 else "N/A" for index in range(rows)],
            "Ngày": ["22/07/2026"] * rows,
        }
    )
    result = DataCleaner(profile="generic").clean(frame)
    return len(result.data)


def benchmark_vietnamese_text(rows: int) -> int:
    values = ("Nguyá»…n VÄƒn A", "Cà   phê\nsữa", "\ufeffTrà\u00a0đào", "không có")
    frame = pd.DataFrame({"Mô tả": [values[index % len(values)] for index in range(rows)]})
    result = DataCleaner(profile="generic", config={"auto_types": False}).clean(frame)
    return len(result.data)


def benchmark_finance(rows: int) -> int:
    amounts = ("1.250.000 VNĐ", "850,000 VND", "(125.000 VNĐ)", "N/A")
    frame = pd.DataFrame(
        {
            "transaction_id": [f"TX-{index:08d}" for index in range(rows)],
            "transaction_date": ["22/07/2026"] * rows,
            "amount": [amounts[index % len(amounts)] for index in range(rows)],
        }
    )
    result = DataCleaner(profile="finance").clean(frame)
    return len(result.data)


def benchmark_csv(rows: int) -> int:
    with tempfile.TemporaryDirectory(prefix="vietclean-benchmark-") as temporary:
        source = Path(temporary) / "million_rows.csv"
        with source.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["order_id", "item_name", "quantity"])
            for index in range(rows):
                writer.writerow([f"ORD-{index:09d}", "Cà phê sữa", index % 10])
        processed = 0
        for chunk in read_chunks(
            source,
            chunksize=min(100_000, rows),
            resource_limits={"max_rows": rows + 1, "max_cells": max(3, rows * 3 + 3)},
        ):
            processed += len(chunk)
        return processed


def run_case(case: str, rows: int | None = None) -> dict[str, float | int | str]:
    """Run one named workload and return aggregate timing only."""

    if case not in DEFAULT_ROWS:
        raise ValueError(f"Benchmark không được hỗ trợ: {case}")
    selected_rows = DEFAULT_ROWS[case] if rows is None else rows
    if isinstance(selected_rows, bool) or not isinstance(selected_rows, int) or selected_rows <= 0:
        raise ValueError("rows phải là số nguyên dương.")
    operations = {
        "dataframe-100k": benchmark_dataframe,
        "csv-1m": benchmark_csv,
        "vietnamese-text": benchmark_vietnamese_text,
        "finance-numeric": benchmark_finance,
    }
    return _measure(case, selected_rows, lambda: operations[case](selected_rows))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=tuple(DEFAULT_ROWS), required=True)
    parser.add_argument("--rows", type=int, help="Override nhỏ để smoke test benchmark.")
    args = parser.parse_args()
    print(json.dumps(run_case(args.case, args.rows), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
