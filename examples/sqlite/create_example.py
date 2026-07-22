"""Create a tiny synthetic SQLite input for the documentation examples."""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3


ROWS = [
    ("SQ-001", "22/07/2026", "SKU-001", "Cà   phê sữa", "2", "45.000 VNĐ"),
    ("SQ-002", "2026-07-22", "SKU-002", "TrÃ  đào", "1", "55,000 VND"),
    ("SQ-002", "bad-date", "SKU-002", "  Trà đào  ", "N/A", "?"),
]


def create_database(output: Path) -> None:
    """Create one database without replacing an existing file."""

    if output.exists():
        raise FileExistsError(f"Đích đã tồn tại: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(output)
    try:
        with connection:
            connection.execute(
                "CREATE TABLE orders ("
                "order_id TEXT, order_date TEXT, sku TEXT, item_name TEXT, "
                "quantity TEXT, unit_price TEXT)"
            )
            connection.executemany(
                "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)",
                ROWS,
            )
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("orders_dirty.sqlite"),
    )
    args = parser.parse_args()
    create_database(args.output.resolve())
    print(f"Đã tạo SQLite synthetic: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
