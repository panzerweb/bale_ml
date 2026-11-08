"""Reproducible synthetic Panabo sale lines. Uses only Python's standard library.

Run from the project root: python scripts/generate_panabo.py
The notebook embeds the same generator and reference snapshot for standalone Colab use.
"""
import argparse
from collections import Counter
import csv
from datetime import date, datetime, time as datetime_time, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random


PANABO_COLUMNS = [
    "transaction_datetime", "known_at", "transaction_id", "transaction_item_id",
    "transaction_status", "store_id", "city", "barangay", "product_id",
    "variant_id", "category_id", "quantity", "unit_label", "sales_channel",
]
PANABO_CATEGORIES = [
    ("demo-beverages", "Beverages", "bottle", "500 mL bottle", 1.25),
    ("demo-snacks", "Snacks", "pack", "30 g pack", 1.10),
    ("demo-canned-goods", "Canned goods", "can", "155 g can", 0.85),
    ("demo-instant-noodles", "Instant noodles", "pack", "55 g pack", 1.00),
]
PANABO_GENERATOR_VERSION = "panabo-synthetic-v1"
PANABO_TZ = timezone(timedelta(hours=8))


def panabo_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def panabo_write_csv(path, columns, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def generate_panabo(directory, end_date="2026-11-08", days=180, rows=50000,
                    seed=42, reference=None):
    """Generate exact-count sale lines plus complete coverage and reference files.

    A rotating one-in-four-day sale floor gives every series seven positive dates
    in every complete 28-day window. Remaining sale lines are weighted draws.
    This floor is an explicit demo assumption, never inferred reporting evidence.
    """
    end = date.fromisoformat(str(end_date))
    if not isinstance(days, int) or days < 84:
        raise ValueError("Use at least 84 complete dates for notebook evaluation.")
    if not isinstance(rows, int) or rows <= 0:
        raise ValueError("rows must be a positive integer")
    if reference is None:
        source = Path(__file__).resolve().parents[1]/"data"/"panabo_reference.json"
        reference = json.loads(source.read_text(encoding="utf-8"))
    areas = reference["areas"]
    if len(areas) != 40 or len({a["area_id"] for a in areas}) != 40:
        raise ValueError("The Panabo profile requires 40 unique barangays.")
    start = end - timedelta(days=days-1)
    dates = [start + timedelta(days=i) for i in range(days)]
    rng = random.Random(seed)
    stores, slots, weights, counts = [], [], [], []
    for a, area in enumerate(areas):
        # Arbitrary synthetic effects, independent of population and geography.
        area_effect = rng.uniform(0.75, 1.35)
        for s in range(2):
            store = {"store_id":f"demo-panabo-{area['area_id']}-{s+1:02d}",
                     "store_name":f"Demo {area['barangay']} Store {s+1}",
                     "area_id":area["area_id"], "city":"Panabo",
                     "barangay":area["barangay"], "data_kind":"synthetic"}
            stores.append(store)
            store_effect = area_effect * rng.uniform(0.8, 1.2)
            for k, category in enumerate(PANABO_CATEGORIES):
                phase = rng.randrange(4)
                trend = rng.uniform(-0.08, 0.18)
                for d, day in enumerate(dates):
                    weekend = 1.25 if day.weekday() >= 5 else 1.0
                    weight = store_effect * category[4] * weekend * (1 + trend*d/(days-1))
                    slots.append((store, k, d))
                    weights.append(weight)
                    counts.append(int(d % 4 == phase))
    floor = sum(counts)
    if rows < floor:
        raise ValueError(f"Need at least {floor} rows for this profile's activity floor; requested {rows}.")
    cumulative, total = [], 0.0
    for weight in weights:
        total += weight
        cumulative.append(total)
    for index in rng.choices(range(len(slots)), cum_weights=cumulative, k=rows-floor):
        counts[index] += 1
    sales, coverage, store_daily, area_daily = [], [], [], Counter()
    for (store, k, d), count, weight in zip(slots, counts, weights):
        day = dates[d]
        category_id, _, unit, _, _ = PANABO_CATEGORIES[k]
        known = datetime.combine(day+timedelta(days=1), datetime_time(0, 5), PANABO_TZ).isoformat()
        coverage.append(dict(store_id=store["store_id"], city="Panabo", barangay=store["barangay"],
            category_id=category_id, date=day.isoformat(), participation_status="active",
            reporting_status="complete", operating_status="open", availability_status="unknown",
            known_at=known, coverage_source=PANABO_GENERATOR_VERSION))
        sold = 0
        for line in range(count):
            # Two fictional products per category share the same package size.
            product = f"{category_id}-product-{rng.randrange(2)+1:02d}"
            quantity = max(1, min(15, int(round(rng.gammavariate(2.2, weight/1.7)))))
            sold += quantity
            event = datetime.combine(day, datetime_time(8, 0), PANABO_TZ) + timedelta(seconds=rng.randrange(14*3600))
            identity = f"demo-panabo:{day.isoformat()}:{store['store_id']}:{k}:{line+1}"
            sales.append(dict(transaction_datetime=event.isoformat(), known_at=known,
                transaction_id=identity, transaction_item_id=identity+":line:1",
                transaction_status="completed", store_id=store["store_id"], city="Panabo",
                barangay=store["barangay"], product_id=product, variant_id=product+"-standard",
                category_id=category_id, quantity=quantity, unit_label=unit,
                sales_channel="online" if rng.random() < 0.18 else "pos"))
        store_daily.append(dict(store_id=store["store_id"], area_id=store["area_id"],
            category_id=category_id, date=day.isoformat(), units_sold=sold,
            observation_status="complete", data_kind="synthetic"))
        area_daily[(store["area_id"], category_id, day.isoformat())] += sold
    sales.sort(key=lambda r:(r["transaction_datetime"], r["transaction_item_id"]))
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    area_columns = ["area_id", "city", "barangay", "latitude", "longitude", "coordinate_source",
                    "coordinate_source_url", "identity_source_url", "source_checked_on"]
    categories = [dict(category_id=c[0], category_label=c[1], unit_label=c[2], package_size=c[3],
                       unit_policy="recorded_sale_units", data_kind="synthetic") for c in PANABO_CATEGORIES]
    products = [dict(product_id=f"{c[0]}-product-{p:02d}", variant_id=f"{c[0]}-product-{p:02d}-standard",
                     product_name=f"Demo {c[1]} {p}", category_id=c[0], unit_label=c[2],
                     package_size=c[3], data_kind="synthetic") for c in PANABO_CATEGORIES for p in (1, 2)]
    tables = {
        "transactions.csv":(PANABO_COLUMNS, sales),
        "coverage.csv":(list(coverage[0]), coverage),
        "areas.csv":(area_columns, [{key:a.get(key, "") for key in area_columns} for a in areas]),
        "stores.csv":(list(stores[0]), stores),
        "categories.csv":(list(categories[0]), categories),
        "products.csv":(list(products[0]), products),
        "store_daily_observations.csv":(list(store_daily[0]), store_daily),
        "area_daily_observations.csv":(["area_id", "category_id", "date", "units_sold", "observation_status", "data_kind"],
            [dict(area_id=a, category_id=c, date=d, units_sold=q, observation_status="complete", data_kind="synthetic")
             for (a,c,d), q in sorted(area_daily.items())]),
    }
    for filename, (columns, records) in tables.items():
        panabo_write_csv(directory/filename, columns, records)
    checksums = {name:panabo_sha256(directory/name) for name in sorted(tables)}
    manifest = {
        "schema_version":"market-demand-v1", "generator_version":PANABO_GENERATOR_VERSION,
        "data_kind":"synthetic", "seed":seed, "start":start.isoformat(), "end":end.isoformat(),
        "days":days, "rows":rows, "area_count":40, "store_count":80, "category_count":4,
        "forecast_start":(end+timedelta(days=1)).isoformat(), "forecast_end":(end+timedelta(days=7)).isoformat(),
        "as_of":datetime.combine(end+timedelta(days=1), datetime_time(0, 15), PANABO_TZ).isoformat(),
        "row_counts":{name:len(table[1]) for name, table in tables.items()},
        "total_recorded_units":sum(r["quantity"] for r in sales),
        "reference_version":reference["reference_version"],
        "reference_sha256":hashlib.sha256(json.dumps(reference, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        "identity_source_url":areas[0]["identity_source_url"],
        "identity_reference_date":reference["identity_reference_date"],
        "coordinate_policy":"Published approximate barangay reference points; not official centroids or store coordinates. Unverified points stay blank.",
        "assumptions":[
            "All sales, stores, products, channels and reporting history are simulated; geography is sourced separately.",
            "Fixed cohort: two stores in every barangay, all four categories, open and completely reported on every date.",
            "Availability is unknown. No-sale dates with complete reporting are zero realized sales.",
            "One positive-sale date every four dates per store/category is reserved for demo eligibility; remaining lines use weighted sampling.",
            "Arbitrary area/store effects, 25% weekend weight increase, category differences and -8% to +18% series trends are synthetic assumptions.",
            "Quantities are bounded gamma draws; 18% online-channel probability; each product has one standard package size.",
            "Records and coverage become known at 00:05 Manila the following day; forecast issuance is 00:15.",
            "Combined category units count packages of different types, not comparable physical consumption.",
            "Synthetic evaluation demonstrates code behavior, not actual Panabo demand or real-world model accuracy.",
        ],
        "files":checksums,
        "dataset_fingerprint":hashlib.sha256(json.dumps(checksums, sort_keys=True).encode()).hexdigest(),
    }
    (directory/"dataset_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    return directory/"transactions.csv", directory/"coverage.csv"


def panabo_preset(directory, reference):
    """Create missing demo input; validate existing inputs before configuring a run."""
    directory = Path(directory)
    manifest_path = directory/"dataset_manifest.json"
    if not manifest_path.exists():
        generate_panabo(directory, reference=reference)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("data_kind") != "synthetic" or manifest.get("generator_version") != PANABO_GENERATOR_VERSION:
        raise ValueError("Incompatible Panabo demo manifest; regenerate with scripts/generate_panabo.py.")
    for filename, checksum in manifest["files"].items():
        if filename not in {"transactions.csv", "coverage.csv", "areas.csv", "stores.csv", "categories.csv", "products.csv",
                            "store_daily_observations.csv", "area_daily_observations.csv"}:
            raise ValueError("Unexpected Panabo demo artifact.")
        if panabo_sha256(directory/filename) != checksum:
            raise ValueError(f"Panabo demo checksum mismatch: {filename}; regenerate the dataset.")
    required = {"transactions.csv", "coverage.csv", "areas.csv"}
    if not required.issubset(manifest["files"]):
        raise ValueError("Panabo demo manifest is missing required inputs.")
    with (directory/"areas.csv").open(encoding="utf-8", newline="") as stream:
        registry = [{k:r[k] for k in ("city", "barangay", "area_id")} for r in csv.DictReader(stream)]
    return {"csv_path":directory/"transactions.csv", "coverage_path":directory/"coverage.csv",
            "coordinates_path":directory/"areas.csv", "area_registry":registry,
            "cutoff":manifest["end"], "as_of":manifest["as_of"], "manifest":manifest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("demo_data/panabo_50k"))
    parser.add_argument("--end-date", default="2026-11-08")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--rows", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    paths = generate_panabo(args.output, args.end_date, args.days, args.rows, args.seed)
    print(f"Generated {args.rows:,} synthetic sale lines: {paths[0]}")
    print(f"Coverage: {paths[1]}")


if __name__ == "__main__":
    main()
