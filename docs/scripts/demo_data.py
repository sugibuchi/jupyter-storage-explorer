"""The demo storage the screenshots and the demo GIFs show: a small sales data
lake of a coffee roaster, with realistic but made-up content.

The explorers show it from fsspec's memory filesystem ("memory:///sales-lake"),
so no path of the computer the pictures are taken on appears in them. The
kernel fills it from a local copy written by ``write``, which also serves the
data browser: polars cannot read the memory filesystem, so ``supports``
read the local copy instead (the explorer still shows memory URLs).

Run as a script to write the data into a folder and list it:
uv run --group docs docs/scripts/demo_data.py <folder>
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import pathlib
import random
import re
import shutil
import sys
from typing import Any

import fsspec
import openpyxl
import polars as pl
import pyarrow.dataset as ds
from deltalake import write_deltalake
from PIL import Image, ImageDraw

from jupyter_storage_explorer.formats import default_supports

# The local copy, set by _lab.py for the kernels of the server it starts.
DATA_ENV = "JSE_DEMO_DATA"
LAKE = "sales-lake"
LAKE_URL = f"memory:///{LAKE}"
SCRATCH_URL = "memory:///scratch"
# A team's folder on the server's disk, which every kernel reaches (unlike
# each kernel's memory): the source of file-transfer.gif's drag.
SHARE = "shared-drive"

FIRST_NAMES = [
    "Aiko", "Haruto", "Yui", "Sota", "Camille", "Louis", "Chloé", "Hugo", "Emma",
    "Liam", "Olivia", "Noah", "Ava", "Lena", "Felix", "Mia", "Jonas", "Sofia",
    "Mateo", "Amara", "Ravi", "Priya", "Lucas", "Ingrid",
]  # fmt: skip
LAST_NAMES = [
    "Tanaka", "Suzuki", "Watanabe", "Martin", "Bernard", "Dubois", "Moreau",
    "Smith", "Johnson", "Garcia", "Miller", "Müller", "Schmidt", "Weber",
    "Fischer", "Rossi", "Okafor", "Patel", "Silva", "Larsen",
]  # fmt: skip
CITIES = {
    "JP": ["Tokyo", "Osaka", "Fukuoka", "Sapporo"],
    "FR": ["Paris", "Lyon", "Bordeaux", "Lille"],
    "US": ["Seattle", "Austin", "Boston", "Portland"],
    "DE": ["Berlin", "Hamburg", "Munich", "Cologne"],
}
PRODUCTS = [
    # sku, product, category, unit price (EUR)
    ("CF-ETH-250", "Ethiopia Yirgacheffe 250g", "Coffee", 12.50),
    ("CF-COL-250", "Colombia Huila 250g", "Coffee", 11.00),
    ("CF-KEN-250", "Kenya AA 250g", "Coffee", 13.90),
    ("CF-HSE-1K", "House Espresso 1kg", "Coffee", 32.00),
    ("CF-DEC-250", "Decaf Colombia 250g", "Coffee", 11.50),
    ("TE-SEN-100", "Sencha Green Tea 100g", "Tea", 8.40),
    ("TE-EGR-100", "Earl Grey 100g", "Tea", 7.20),
    ("RD-CBC-1L", "Cold Brew Concentrate 1L", "Ready to drink", 14.00),
    ("EQ-V60-02", "Ceramic Pour-Over Dripper", "Equipment", 24.00),
    ("EQ-GRN-01", "Hand Grinder", "Equipment", 59.00),
]
CHANNELS = ["web", "web", "web", "app", "app", "store", "wholesale"]


def customers(rng: random.Random, n: int = 200) -> Any:
    countries = [rng.choice(list(CITIES)) for _ in range(n)]
    first = [rng.choice(FIRST_NAMES) for _ in range(n)]
    last = [rng.choice(LAST_NAMES) for _ in range(n)]
    return pl.DataFrame(
        {
            "customer_id": [f"C{10001 + i}" for i in range(n)],
            "name": [f"{f} {la}" for f, la in zip(first, last, strict=True)],
            "email": [
                f"{f.lower()}.{la.lower()}{i % 97}@example.com".replace("é", "e").replace("ü", "u")
                for i, (f, la) in enumerate(zip(first, last, strict=True))
            ],
            "city": [rng.choice(CITIES[c]) for c in countries],
            "country": countries,
            "segment": [rng.choice(["consumer"] * 4 + ["cafe", "office"]) for _ in range(n)],
            "signup_date": [
                dt.date(2022, 1, 1) + dt.timedelta(days=rng.randrange(1300)) for _ in range(n)
            ],
        }
    )  # fmt: skip


def orders(rng: random.Random, people: Any, n: int = 2400) -> Any:
    start = dt.datetime(2025, 1, 1, 6)
    ids = people["customer_id"].to_list()
    country = dict(zip(ids, people["country"], strict=True))
    rows = []
    for _ in range(n):
        sku, product, _, price = rng.choice(PRODUCTS)
        customer = rng.choice(ids)
        channel = rng.choice(CHANNELS)
        bulk = channel == "wholesale"
        rows.append(
            {
                "order_ts": start
                + dt.timedelta(days=rng.randrange(638), minutes=rng.randrange(16 * 60)),
                "customer_id": customer,
                "country": country[customer],
                "channel": channel,
                "sku": sku,
                "product": product,
                "quantity": rng.randrange(6, 25) if bulk else rng.choice([1, 1, 1, 2, 2, 3, 4]),
                "unit_price": round(price * (0.85 if bulk else 1.0), 2),
                "status": rng.choices(["completed", "refunded", "cancelled"], [94, 3, 3])[0],
            }
        )  # fmt: skip
    df = pl.DataFrame(rows).sort("order_ts")
    return df.with_columns(
        order_id=pl.int_range(100001, 100001 + df.height),
        amount=(pl.col("quantity") * pl.col("unit_price")).round(2),
    ).select(
        "order_id", "order_ts", *[c for c in df.columns if c != "order_ts"], "amount"
    )


def events(rng: random.Random, people: Any, day: dt.date) -> str:
    ids = people["customer_id"].to_list()
    lines = []
    t = dt.datetime.combine(day, dt.time(7))
    for _ in range(80):
        session = f"s-{rng.randrange(16**8):08x}"
        user = rng.choice(ids) if rng.random() < 0.6 else None
        device = rng.choice(["desktop", "mobile", "mobile", "tablet"])
        steps = ["page_view"] * rng.randrange(1, 4)
        if rng.random() < 0.4:
            steps.append("add_to_cart")
            if rng.random() < 0.5:
                steps.append("purchase")
        sku = rng.choice(PRODUCTS)[0]
        for step in steps:
            t += dt.timedelta(seconds=rng.randrange(5, 240))
            event: dict[str, Any] = {
                "ts": t.isoformat() + "Z",
                "session_id": session,
                "user_id": user,
                "event": step,
                "device": device,
            }
            if step == "page_view":
                event["page"] = rng.choice(
                    ["/", "/coffee", "/tea", f"/p/{sku.lower()}"]
                )
            else:
                event["items"] = [{"sku": sku, "quantity": rng.choice([1, 1, 2])}]
            lines.append(json.dumps(event, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def chart(monthly: list[tuple[str, float]]) -> bytes:
    """A bar chart of revenue by month, as a PNG."""
    width, height, pad = 640, 320, 36
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    top = max(v for _, v in monthly)
    bar = (width - 2 * pad) / len(monthly)
    for i, (month, value) in enumerate(monthly):
        x = pad + i * bar
        y = height - pad - (height - 2 * pad) * value / top
        draw.rectangle([x + 3, y, x + bar - 3, height - pad], fill="#4c78a8")
        if month.endswith(("-01", "-07")):
            draw.text((x, height - pad + 6), month, fill="#555555")
    draw.line([pad, height - pad, width - pad, height - pad], fill="#999999")
    draw.text((pad, 10), "Revenue by month (EUR)", fill="#222222")
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def write(root: pathlib.Path) -> None:
    """Write the demo lake into ``root``/sales-lake (replacing it)."""
    rng = random.Random(7)
    lake = root / LAKE
    shutil.rmtree(lake, ignore_errors=True)
    for folder in (
        "landing/orders",
        "landing/events",
        "curated",
        "pipelines",
        "reports",
    ):
        (lake / folder).mkdir(parents=True)

    people = customers(rng)
    sales = orders(rng, people)

    # landing/: files as the shop's systems deliver them.
    for month in ("2026-07", "2026-08", "2026-09"):
        part = sales.filter(pl.col("order_ts").dt.strftime("%Y-%m") == month)
        part.write_csv(
            lake / "landing" / "orders" / f"orders_{month}.csv",
            datetime_format="%Y-%m-%d %H:%M:%S",
        )
    for day in (28, 29, 30):
        text = events(rng, people, dt.date(2026, 9, day))
        (lake / "landing" / "events" / f"events_2026-09-{day}.jsonl").write_text(
            text, encoding="utf-8"
        )
    pl.DataFrame(
        PRODUCTS, schema=["sku", "product", "category", "unit_price"], orient="row"
    ).write_csv(lake / "landing" / "products.tsv", separator="\t")

    # curated/: cleaned tables.
    sales.write_parquet(lake / "curated" / "orders.parquet")
    by_month = sales.with_columns(
        year=pl.col("order_ts").dt.year(), month=pl.col("order_ts").dt.month()
    )
    ds.write_dataset(
        by_month.to_arrow(),
        lake / "curated" / "orders_by_month",
        format="parquet",
        partitioning=["year", "month"],
        partitioning_flavor="hive",
        basename_template="part-0000{i}-3f2a9c1e.snappy.parquet",
    )
    (lake / "curated" / "orders_by_month" / "_SUCCESS").write_text("")
    table = lake / "curated" / "customers"
    write_deltalake(table, people.head(170).to_arrow(), partition_by=["country"], name="customers",
                    description="Customers, one row each, from the shop and wholesale accounts")  # fmt: skip
    write_deltalake(table, people.tail(30).to_arrow(), mode="append")

    # pipelines/: how the lake is fed.
    (lake / "pipelines" / "README.md").write_text(
        "# Sales lake\n\n"
        "Orders, customers and web events of the online shop, the café and wholesale.\n\n"
        "| Folder | Contents | Refreshed |\n"
        "|---|---|---|\n"
        "| `landing/` | Files as delivered: monthly orders (CSV), web events (JSON Lines) | Daily, 03:00 UTC |\n"
        "| `curated/` | Cleaned tables: `orders` (Parquet), `customers` (Delta Lake) | Daily, 04:00 UTC |\n"
        "| `reports/` | Monthly figures for finance | First of each month |\n\n"
        "Owner: data platform team. Questions: #sales-data.\n",
        encoding="utf-8",
    )
    (lake / "pipelines" / "daily_orders.yaml").write_text(
        "pipeline: daily_orders\n"
        'schedule: "0 3 * * *"\n'
        "steps:\n"
        "  - ingest:\n      from: landing/orders/orders_*.csv\n      schema: schemas/orders.json\n"
        "  - dedupe: {key: order_id}\n"
        "  - write:\n      to: curated/orders_by_month\n      partition_by: [year, month]\n"
        'alerts:\n  - on: failure\n    notify: "#sales-data"\n',
        encoding="utf-8",
    )
    (lake / "pipelines" / "monthly_revenue.sql").write_text(
        "-- Revenue by month and channel, completed orders only.\n"
        "SELECT date_trunc('month', order_ts) AS month,\n"
        "       channel,\n"
        "       count(*)    AS orders,\n"
        "       sum(amount) AS revenue\n"
        "FROM curated.orders\n"
        "WHERE status = 'completed'\n"
        "GROUP BY 1, 2\n"
        "ORDER BY 1, 2;\n",
        encoding="utf-8",
    )
    (lake / "pipelines" / "ingest.log").write_text(
        "".join(
            f"2026-09-{d:02d}T03:00:{rng.randrange(5, 50):02d}Z INFO daily_orders finished "
            f"rows={rng.randrange(90, 140)} duration={rng.uniform(20, 60):.1f}s\n"
            for d in range(21, 31)
        ),
        encoding="utf-8",
    )

    # reports/: for finance.
    monthly = (
        sales.filter(pl.col("status") == "completed")
        .group_by(month=pl.col("order_ts").dt.strftime("%Y-%m"))
        .agg(pl.col("amount").sum())
        .sort("month")
    )
    (lake / "reports" / "revenue_by_month.png").write_bytes(
        chart(list(monthly.iter_rows()))
    )
    workbook = openpyxl.Workbook()
    budget = workbook.active
    budget.title = "Budget 2026"
    budget.append(["month", "channel", "planned_eur", "actual_eur"])
    for month in range(1, 10):
        for channel in ("web", "app", "store", "wholesale"):
            planned = rng.randrange(8, 30) * 100
            budget.append(
                [
                    f"2026-{month:02d}",
                    channel,
                    planned,
                    round(planned * rng.uniform(0.8, 1.2), 2),
                ]
            )
    workbook.create_sheet("Notes").append(
        ["Figures in EUR, excluding VAT. Actuals are updated monthly."]
    )
    workbook.save(lake / "reports" / "budget_2026.xlsx")
    (lake / "catalog.json").write_text(
        json.dumps(
            [
                {"name": "orders", "path": "curated/orders.parquet", "owner": {"team": "sales", "contact": "sales-data@example.com"},
                 "columns": sales.columns, "refresh": "daily"},
                {"name": "customers", "path": "curated/customers", "format": "delta", "owner": {"team": "crm", "contact": "crm@example.com"},
                 "columns": people.columns, "refresh": "daily"},
            ],
            indent=2,
        ),
        encoding="utf-8",
    )  # fmt: skip
    stamp(lake, rng)


def write_share(root: pathlib.Path) -> None:
    """Write a team's shared folder into ``root``/shared-drive (replacing it),
    for file-transfer.gif only: other pictures do not show it in JupyterLab's
    file browser."""
    rng = random.Random(7)
    share = root / SHARE
    shutil.rmtree(share, ignore_errors=True)
    (share / "pricing").mkdir(parents=True)
    pl.DataFrame(
        PRODUCTS, schema=["sku", "product", "category", "unit_price"], orient="row"
    ).with_columns(price_2027=(pl.col("unit_price") * 1.04).round(2)).write_csv(
        share / "pricing" / "price_list_2027.csv"
    )
    (share / "pricing" / "README.md").write_text(
        "# Pricing\n\nPrice lists agreed with finance, one file per year.\n",
        encoding="utf-8",
    )
    (share / "meeting_notes.md").write_text(
        "# Sales sync, 2026-10-14\n\n- New price list from January.\n",
        encoding="utf-8",
    )
    stamp(share, rng)


def stamp(lake: pathlib.Path, rng: random.Random) -> None:
    """Give the files modification times as if the pipelines wrote them:
    a day's or a month's files the next morning, the rest on October 1st."""
    for path in lake.rglob("*"):
        if not path.is_file():
            continue
        name = path.relative_to(lake).as_posix()
        if m := re.search(r"(\d{4})-(\d{2})-(\d{2})", name):
            when = dt.datetime(*map(int, m.groups())) + dt.timedelta(days=1)
        elif m := re.search(r"(\d{4})-(\d{2})\b", name):
            year, month = map(int, m.groups())
            when = dt.datetime(year + month // 12, month % 12 + 1, 1)
        elif m := re.search(r"year=(\d+)/month=(\d+)/", name):
            year, month = map(int, m.groups())
            when = dt.datetime(year + month // 12, month % 12 + 1, 1, 1)
        elif name.startswith(("pipelines/", "catalog")):
            when = dt.datetime(2026, 9, rng.randrange(2, 20), 9)
        else:
            when = dt.datetime(2026, 10, 1, 1)
        when += dt.timedelta(
            hours=3, minutes=rng.randrange(60), seconds=rng.randrange(60)
        )
        t = when.replace(tzinfo=dt.UTC).timestamp()
        os.utime(path, (t, t))


# In the kernel.


def shared_drive() -> dict[str, Any]:
    """The team's shared folder, a storage of the server's disk: a
    ``DirFileSystem``, so its paths start at the folder."""
    from fsspec.implementations.dirfs import DirFileSystem  # noqa: PLC0415

    folder = (local_copy() / SHARE).as_posix()
    return {"Shared drive": DirFileSystem(folder, fsspec.filesystem("file"))}


def local_copy() -> pathlib.Path:
    return pathlib.Path(os.environ[DATA_ENV])


def filesystems() -> dict[str, str]:
    """The demo storages, filled from the local copy: "Sales lake", and an
    empty "Scratch"."""
    fs = fsspec.filesystem("memory")
    if not fs.exists(f"/{LAKE}"):
        src = local_copy() / LAKE
        for path in sorted(src.rglob("*")):
            if path.is_file():
                key = f"/{LAKE}/{path.relative_to(src).as_posix()}"
                fs.pipe_file(key, path.read_bytes())
                # The memory filesystem's only time, shown as the modification time.
                fs.store[key].created = dt.datetime.fromtimestamp(
                    path.stat().st_mtime, dt.UTC
                )
        fs.mkdir("/scratch")
        fs.pipe_file("/scratch/exports/.keep", b"")
    return {"Sales lake": LAKE_URL, "Scratch": SCRATCH_URL}


def supports() -> list[Any]:
    """The default supports, polars' viewing the local copy (it reads by URL,
    for the data browser), for an explorer's ``supports``: tried before its
    own defaults, they are those used."""

    from jupyter_storage_explorer.filesystems import (  # noqa: PLC0415
        LocalLocation,
        MapperChain,
        MemoryLocation,
        default_mappers,
    )

    local_fs = fsspec.filesystem("file")
    mappers = MapperChain(default_mappers())

    def local(location, fs, path):
        """The local copy's location, filesystem and path of a demo item, if
        it has one (Scratch's files are in memory only)."""
        if not isinstance(location, MemoryLocation):
            return location, fs, path
        copy = (local_copy() / location.path.lstrip("/")).as_posix()
        if not local_fs.exists(copy):
            return location, fs, path
        copy_location = mappers.location_of(local_fs, copy)
        assert isinstance(copy_location, LocalLocation)
        return copy_location, local_fs, copy

    result = default_supports()
    for support in result:
        # Only polars reads by URL; the others read the demo's own files,
        # so that files saved from JupyterLab show as saved.
        uses_polars = support.use is not None and support.use.package == "polars"
        if uses_polars and "view" in support.capabilities:
            view = support.view
            support.view = lambda fmt, location, fs, path, is_dir, view=view, **kw: (
                view(fmt, *local(location, fs, path), is_dir, **kw)
            )
    return result


if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1])
    write(out)
    for p in sorted((out / LAKE).rglob("*")):
        if p.is_file():
            print(f"{p.stat().st_size:>8,}  {p.relative_to(out).as_posix()}")
