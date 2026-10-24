"""Create notebooks/samples/: one or more samples of each format the browser can preview.

Run with: uv run notebooks/make_samples.py
Needs the dev dependencies (polars, pyarrow, deltalake, openpyxl, duckdb).
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import random
import shutil
import struct
import zlib

import duckdb
import openpyxl
import polars as pl
import pyarrow.dataset as ds
from deltalake import write_deltalake

OUT = pathlib.Path(__file__).parent / "samples"
rng = random.Random(42)


def orders(n: int) -> pl.DataFrame:
    start = dt.date(2025, 1, 1)
    return pl.DataFrame(
        {
            "order_id": range(1, n + 1),
            "order_date": [
                start + dt.timedelta(days=rng.randrange(540)) for _ in range(n)
            ],
            "customer_id": [rng.randrange(1, 51) for _ in range(n)],
            "product": [
                rng.choice(["Coffee", "Tea", "Cocoa", "Juice", "Water"])
                for _ in range(n)
            ],
            "quantity": [rng.randrange(1, 10) for _ in range(n)],
            "unit_price": [rng.choice([2.5, 3.0, 3.75, 4.2, 1.1]) for _ in range(n)],
        }
    ).sort("order_date")


def write_png(path: pathlib.Path, width: int, height: int) -> None:
    """A small gradient PNG, written without an imaging library."""
    rows = b"".join(
        b"\x00"
        + bytes(
            c for x in range(width) for c in (x * 255 // width, y * 255 // height, 160)
        )
        for y in range(height)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def docs(out: pathlib.Path) -> None:
    out.mkdir()
    (out / "notes.md").write_text(
        "# Sample data lake\n\n"
        "- `raw/`: files as delivered (CSV, TSV, JSON, JSON Lines, Excel)\n"
        "- `lake/`: curated data (Parquet file, partitioned Parquet dataset, Delta Lake table, DuckDB database)\n"
        "- `images/`: PNG and SVG\n",
        encoding="utf-8",
    )
    (out / "pipeline.yaml").write_text(
        'pipeline: daily_orders\nschedule: "0 3 * * *"\nsteps:\n  - ingest: raw/orders.csv\n  - write: lake/orders_by_month\n',
        encoding="utf-8",
    )
    (out / "monthly_revenue.sql").write_text(
        "SELECT date_trunc('month', order_date) AS month,\n"
        "       sum(quantity * unit_price) AS revenue\n"
        "FROM orders\nGROUP BY 1\nORDER BY 1;\n",
        encoding="utf-8",
    )
    (out / "ingest.log").write_text(
        "".join(
            f"2026-10-0{d}T03:00:{s:02d}Z INFO ingest finished rows={rng.randrange(400, 600)}\n"
            for d in range(1, 8)
            for s in (12,)
        ),
        encoding="utf-8",
    )


def raw(out: pathlib.Path, df: pl.DataFrame) -> None:
    out.mkdir()
    df.write_csv(out / "orders.csv")
    pl.DataFrame(
        {
            "product": ["Coffee", "Tea", "Cocoa", "Juice", "Water"],
            "category": ["Hot", "Hot", "Hot", "Cold", "Cold"],
            "caffeine": [True, True, False, False, False],
        }
    ).write_csv(out / "products.tsv", separator="\t")
    datasets = [
        {"name": "orders", "owner": {"team": "sales", "contact": "sales@example.com"}, "columns": df.columns,
         "refresh": "daily"},
        {"name": "customers", "owner": {"team": "crm", "contact": "crm@example.com"},
         "columns": ["customer_id", "name", "country", "since"], "refresh": "weekly"},
    ]  # fmt: skip
    (out / "datasets.json").write_text(json.dumps(datasets, indent=2), encoding="utf-8")
    events = [
        {"ts": f"2026-10-01T09:{m:02d}:00Z", "user": rng.randrange(1, 51), "event": rng.choice(["view", "cart", "buy"]),
         **({"items": [rng.choice(["Coffee", "Tea"])]} if rng.random() < 0.4 else {})}
        for m in range(60)
    ]  # fmt: skip
    (out / "events.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8"
    )

    workbook = openpyxl.Workbook()
    budget = workbook.active
    budget.title = "Budget"
    budget.append(["month", "planned", "actual", "on_track"])
    for month in range(1, 13):
        planned = 1000 + month * 50
        actual = round(planned * rng.uniform(0.85, 1.15), 2)
        budget.append([f"2026-{month:02d}", planned, actual, actual >= planned * 0.95])
    notes = workbook.create_sheet("Notes")
    notes.append(["Figures in EUR. Actuals are updated monthly."])
    workbook.save(out / "budget.xlsx")


def lake(out: pathlib.Path, df: pl.DataFrame) -> None:
    out.mkdir()
    df.write_parquet(out / "orders.parquet")

    # Hive-partitioned dataset laid out like Spark output.
    monthly = df.with_columns(
        year=pl.col("order_date").dt.year(), month=pl.col("order_date").dt.month()
    )
    ds.write_dataset(
        monthly.to_arrow(),
        out / "orders_by_month",
        format="parquet",
        partitioning=["year", "month"],
        partitioning_flavor="hive",
        basename_template="part-0000{i}-sample.snappy.parquet",
    )
    (out / "orders_by_month" / "_SUCCESS").write_text("")

    # Delta Lake table with two commits.
    customers = pl.DataFrame(
        {
            "customer_id": range(1, 51),
            "name": [f"Customer {i}" for i in range(1, 51)],
            "country": [rng.choice(["JP", "FR", "US", "DE"]) for _ in range(50)],
            "since": [
                dt.date(2020, 1, 1) + dt.timedelta(days=rng.randrange(2000))
                for _ in range(50)
            ],
        }
    )
    table = out / "customers"
    write_deltalake(table, customers.head(40).to_arrow(), partition_by=["country"], name="customers",
                    description="Sample customers")  # fmt: skip
    write_deltalake(table, customers.tail(10).to_arrow(), mode="append")

    # DuckDB database: tables in two schemas and a view, as the browser lists them.
    # Blocks of 16 kB, not the default 256 kB, keep the file near 100 kB instead of 1 MB.
    with duckdb.connect() as con:
        path = (out / "warehouse.duckdb").as_posix()
        con.execute(f"ATTACH '{path}' AS warehouse (BLOCK_SIZE 16384)")
        con.execute("USE warehouse")
        con.register("orders_df", df.to_arrow())
        con.register("customers_df", customers.to_arrow())
        con.execute("CREATE TABLE orders AS SELECT * FROM orders_df")
        con.execute("CREATE TABLE customers AS SELECT * FROM customers_df")
        con.execute(
            "CREATE VIEW monthly_revenue AS"
            " SELECT date_trunc('month', order_date) AS month,"
            " sum(quantity * unit_price) AS revenue FROM orders GROUP BY 1 ORDER BY 1"
        )
        con.execute("CREATE SCHEMA staging")
        con.execute(
            "CREATE TABLE staging.orders_today AS"
            " SELECT * FROM orders ORDER BY order_date DESC LIMIT 20"
        )
        con.execute("CHECKPOINT")


def images(out: pathlib.Path) -> None:
    out.mkdir()
    write_png(out / "gradient.png", 160, 90)
    (out / "pipeline.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="80" font-family="sans-serif" font-size="14">'
        '<rect x="10" y="20" width="80" height="40" rx="6" fill="#4c78a8"/>'
        '<text x="50" y="45" fill="white" text-anchor="middle">raw</text>'
        '<path d="M95 40 H135" stroke="#555" stroke-width="2"/>'
        '<rect x="140" y="20" width="80" height="40" rx="6" fill="#59a14f"/>'
        '<text x="180" y="45" fill="white" text-anchor="middle">lake</text>'
        "</svg>",
        encoding="utf-8",
    )


def main() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir()
    df = orders(500)
    docs(OUT / "docs")
    raw(OUT / "raw", df)
    lake(OUT / "lake", df)
    images(OUT / "images")
    for path in sorted(OUT.rglob("*")):
        if path.is_file():
            print(f"{path.stat().st_size:>8,}  {path.relative_to(OUT).as_posix()}")


if __name__ == "__main__":
    main()
