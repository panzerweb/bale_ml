"""Prepare a file-only synthetic Colab handoff using existing backend catalog IDs.

No database connection, business-row inserts, training, or uploaded-model loading.
The existing notebook remains the owner of model features/evaluation/export.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import csv
from datetime import date, datetime, time, timedelta
import hashlib
import json
from pathlib import Path
import random
import re
import unicodedata
import zipfile

from generate_panabo import PANABO_COLUMNS, PANABO_TZ, panabo_sha256, panabo_write_csv

ROOT = Path(__file__).resolve().parents[1]
VERSION = "backend-catalog-synthetic-v1"
ZIP_NAME = "Bale_Backend_Demo_Inputs.zip"
NOTEBOOK_NAME = "Bale_Backend_Demo_Colab.ipynb"
UNIT = "sellable_unit"


def normalized(value, *, barangay=False):
    value = " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())
    return re.sub(r"^(?:barangay|brgy\.?|brg\.?)\s+", "", value).strip() if barangay else value


def native_id(value):
    if isinstance(value, bool) or not str(value).isdigit() or int(value) < 1:
        raise ValueError("Catalog IDs must be positive backend integers.")
    return str(int(value))


def load_catalog(path, reference):
    source = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if source.get("contract") != "market-demand-catalog-v1" or not source.get("variants"):
        raise ValueError("Expected the nonempty market-demand-export-catalog JSON snapshot.")
    city_aliases = {"panabo city": "panabo", "city of panabo": "panabo"}
    registry = {(normalized(a["city"]), normalized(a["barangay"], barangay=True)): a for a in reference["areas"]}
    stores, categories, variants, groups = {}, {}, {}, defaultdict(list)
    products = {}
    for raw in source["variants"]:
        row = dict(raw)
        for key in ("store_id", "category_id", "product_id", "variant_id"):
            row[key] = native_id(row[key])
        key = (city_aliases.get(normalized(row.get("city") or ""), normalized(row.get("city") or "")),
               normalized(row.get("barangay") or "", barangay=True))
        if key not in registry:
            raise ValueError(f"Store {row['store_id']} has an unreviewed location: {raw.get('city')!r}/{raw.get('barangay')!r}.")
        area = registry[key]
        store = {"store_id": row["store_id"], "store_name": row["store_name"], "area_id": area["area_id"],
                 "city": area["city"], "barangay": area["barangay"]}
        if row["store_id"] in stores and stores[row["store_id"]] != store:
            raise ValueError("Conflicting locations or names for one store.")
        stores[row["store_id"]] = store
        if row["category_id"] in categories and categories[row["category_id"]] != row["category_name"]:
            raise ValueError("Conflicting category labels.")
        categories[row["category_id"]] = row["category_name"]
        product = (row["store_id"], row["category_id"], row["product_name"])
        if row["product_id"] in products and products[row["product_id"]] != product:
            raise ValueError("Conflicting product/store/category identity.")
        products[row["product_id"]] = product
        if row["variant_id"] in variants:
            raise ValueError("Duplicate variant identity in catalog.")
        attributes = row.get("variant_attributes") or {}
        if not isinstance(attributes, dict):
            raise ValueError("Variant attributes must be an object or null.")
        description = "; ".join(f"{key}={value}" for key, value in sorted(attributes.items()))
        row["package_description"] = ("One sellable variant unit" + ("; " + description if description else ""))[:255]
        variants[row["variant_id"]] = row
        groups[(row["store_id"], row["category_id"])].append(row)
    for rows in groups.values():
        rows.sort(key=lambda row: int(row["variant_id"]))
    areas = [dict(a) for a in reference["areas"] if a["area_id"] in {s["area_id"] for s in stores.values()}]
    return stores, categories, variants, dict(sorted(groups.items(), key=lambda item: tuple(map(int, item[0])))), areas


def generate_inputs(catalog_path, directory, *, days=180, rows=50000, end_date=None, seed=42):
    if not isinstance(days, int) or days < 84 or not isinstance(rows, int) or rows < 1:
        raise ValueError("Use at least 84 historical dates and a positive sale-line budget.")
    end = date.fromisoformat(str(end_date)) if end_date else datetime.now(PANABO_TZ).date() - timedelta(days=1)
    if end >= datetime.now(PANABO_TZ).date():
        raise ValueError("Synthetic history must end before the current Manila day.")
    reference = json.loads((ROOT / "data/panabo_reference.json").read_text(encoding="utf-8"))
    stores, categories, variants, groups, areas = load_catalog(catalog_path, reference)
    start = end - timedelta(days=days - 1)
    dates = [start + timedelta(days=index) for index in range(days)]
    rng = random.Random(seed)
    slots, weights, counts = [], [], []
    # Reuse the Panabo fixture's disclosed activity-floor/weighted-sales
    # convention, with only store/category groups actually present in catalog.
    for group in groups:
        effect, trend, phase = rng.uniform(.75, 1.35), rng.uniform(-.08, .18), rng.randrange(4)
        for index, observed in enumerate(dates):
            slots.append((group, index))
            weights.append(effect * (1.25 if observed.weekday() >= 5 else 1) * (1 + trend * index / (days - 1)))
            counts.append(int(index % 4 == phase))
    floor = sum(counts)
    if rows < floor:
        raise ValueError(f"At least {floor} sale lines are required for this catalog's synthetic activity floor.")
    for index in rng.choices(range(len(slots)), weights=weights, k=rows - floor):
        counts[index] += 1
    sales, coverage, store_daily, area_daily = [], [], [], Counter()
    for ((store_id, category_id), day_index), count, weight in zip(slots, counts, weights):
        store, observed = stores[store_id], dates[day_index]
        known = datetime.combine(observed + timedelta(days=1), time(0, 5), PANABO_TZ).isoformat()
        coverage.append({"store_id": store_id, "city": store["city"], "barangay": store["barangay"],
            "category_id": category_id, "date": observed.isoformat(), "participation_status": "active",
            "reporting_status": "complete", "operating_status": "open", "availability_status": "unknown",
            "known_at": known, "coverage_source": VERSION})
        sold = 0
        for line_number in range(count):
            variant = rng.choice(groups[(store_id, category_id)])
            quantity = max(1, min(15, int(round(rng.gammavariate(2.2, weight / 1.7)))))
            event = datetime.combine(observed, time(8), PANABO_TZ) + timedelta(seconds=rng.randrange(14 * 3600))
            identity = f"synthetic-backend:{observed}:{store_id}:{category_id}:{line_number + 1}"
            sales.append(dict(zip(PANABO_COLUMNS, [event.isoformat(), known, identity, identity + ":line:1", "completed",
                store_id, store["city"], store["barangay"], variant["product_id"], variant["variant_id"], category_id,
                quantity, UNIT, "online" if rng.random() < .18 else "pos"])))
            sold += quantity
        store_daily.append({"store_id": store_id, "area_id": store["area_id"], "category_id": category_id,
                            "date": observed.isoformat(), "units_sold": sold, "observation_status": "complete", "data_kind": "synthetic"})
        area_daily[(store["area_id"], category_id, observed.isoformat())] += sold
    sales.sort(key=lambda row: (row["transaction_datetime"], row["transaction_item_id"]))
    category_rows = [{"category_id": key, "label": label, "unit_label": UNIT, "unit_policy": "recorded_sale_units"}
                     for key, label in sorted(categories.items(), key=lambda item: int(item[0]))]
    product_rows = [{key: row.get(key, "") for key in ("store_id", "product_id", "product_name", "variant_id", "category_id", "sku", "package_description")}
                    | {"unit_label": UNIT} for row in sorted(variants.values(), key=lambda row: int(row["variant_id"]))]
    tables = {
        "transactions.csv": (PANABO_COLUMNS, sales), "coverage.csv": (list(coverage[0]), coverage),
        "areas.csv": (["area_id", "city", "barangay", "latitude", "longitude", "coordinate_source"], areas),
        "stores.csv": (list(next(iter(stores.values()))), list(stores.values())),
        "categories.csv": (list(category_rows[0]), category_rows), "products.csv": (list(product_rows[0]), product_rows),
        "store_daily_observations.csv": (list(store_daily[0]), store_daily),
        "area_daily_observations.csv": (["area_id", "category_id", "date", "units_sold", "observation_status", "data_kind"],
            [{"area_id": area, "category_id": category, "date": observed, "units_sold": quantity,
              "observation_status": "complete", "data_kind": "synthetic"} for (area, category, observed), quantity in sorted(area_daily.items())]),
    }
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    for name, (columns, records) in tables.items():
        # The writer rejects extra columns; geography's source-only fields are
        # retained in the original snapshot rather than misrepresented as inputs.
        panabo_write_csv(directory / name, columns, [{key: row.get(key, "") for key in columns} for row in records])
    checksums = {name: panabo_sha256(directory / name) for name in sorted(tables)}
    manifest = {"schema_version": "market-demand-v1", "generator_version": VERSION, "data_kind": "synthetic",
        "source_catalog_sha256": panabo_sha256(catalog_path), "seed": seed, "days": days, "rows": rows,
        "start": start.isoformat(), "end": end.isoformat(), "as_of": datetime.combine(end + timedelta(days=1), time(0, 15), PANABO_TZ).isoformat(),
        "forecast_start": (end + timedelta(days=1)).isoformat(), "forecast_end": (end + timedelta(days=7)).isoformat(),
        "stores": len(stores), "areas": len(areas), "categories": len(categories), "variants": len(variants),
        "store_category_groups": len(groups), "area_category_groups": len({(a, c) for a, c, _ in area_daily}),
        "recorded_units": sum(row["quantity"] for row in sales), "row_counts": {name: len(records) for name, (_, records) in tables.items()},
        "files": checksums, "assumptions": [
            "Store/catalog identities and location labels come from the existing backend catalog snapshot. No sales came from its database.",
            "All transactions, quantities, channels and complete-reporting statements are generated, and remain synthetic.",
            "Only actual store/category catalog groups participate; unrepresented barangays/stores are not fabricated.",
            "One positive sale every four dates is reserved for eligibility. Other lines use seeded synthetic weekday/trend/noise weights.",
            "All participating groups report completely and are open throughout the period. Stock availability stays unknown.",
            "Each sellable_unit is one catalog variant package/item. Package contents are not converted to kg, mL, or individual contents.",
            "Current category package mixes may vary. Category totals count mixed sellable units, not equivalent physical consumption.",
            "Both simulated sales and reporting statements become known at 00:05 next day, before 00:15 forecast issuance.",
            "Approximate area reference coordinates are not individual store positions or official centroids.",
            "Synthetic evaluation verifies behavior, not actual store demand or real predictive accuracy.",
        ]}
    (directory / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    mappings = {"areas": [{key: a[key] if key not in {"latitude", "longitude"} else float(a[key]) if a[key] else None
                           for key in ("area_id", "city", "barangay", "latitude", "longitude", "coordinate_source")} for a in areas],
                "stores": [{"store_id": int(s["store_id"]), "area_id": s["area_id"], "data_kind": "synthetic",
                            "source_store_id": "backend-store-" + s["store_id"]} for s in stores.values()],
                "units": [{"variant_id": int(row["variant_id"]), "unit_label": UNIT, "package_description": row["package_description"]} for row in variants.values()]}
    (directory / "backend_mappings.json").write_text(json.dumps(mappings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with zipfile.ZipFile(directory / ZIP_NAME, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in [*sorted(tables), "dataset_manifest.json"]:
            archive.write(directory / name, arcname=name)
    return manifest


INPUT_LOADER = '''# Upload the generated input ZIP once. No backend connection is needed in Colab.
from pathlib import Path
import hashlib as _bale_hashlib
import io as _bale_io
import json as _bale_json
import zipfile as _bale_zipfile

BALE_INPUT_DIR = Path("backend_demo_inputs")
_bale_zip = Path("Bale_Backend_Demo_Inputs.zip")
if _bale_zip.exists():
    _bale_bytes = _bale_zip.read_bytes()
else:
    try:
        from google.colab import files as _bale_colab_files
    except ImportError as error:
        raise FileNotFoundError("Place Bale_Backend_Demo_Inputs.zip beside this notebook, then rerun.") from error
    print("Choose Bale_Backend_Demo_Inputs.zip in the upload dialog.")
    _bale_upload = _bale_colab_files.upload()
    if len(_bale_upload) != 1:
        raise ValueError("Upload exactly one input ZIP.")
    _bale_name, _bale_bytes = next(iter(_bale_upload.items()))
    if not _bale_name.lower().endswith(".zip"):
        raise ValueError("Select the input ZIP, not the notebook or a results ZIP.")
_bale_expected = {"transactions.csv", "coverage.csv", "areas.csv", "stores.csv", "categories.csv", "products.csv",
                  "store_daily_observations.csv", "area_daily_observations.csv", "dataset_manifest.json"}
with _bale_zipfile.ZipFile(_bale_io.BytesIO(_bale_bytes)) as _bale_archive:
    _bale_entries = _bale_archive.infolist()
    if (len(_bale_entries) != len(_bale_expected) or {i.filename for i in _bale_entries} != _bale_expected
            or sum(i.file_size for i in _bale_entries) > 100 * 1024 * 1024):
        raise ValueError("Unexpected, duplicate or oversized input ZIP members.")
    _bale_files = {name: _bale_archive.read(name) for name in _bale_expected}
_bale_manifest = _bale_json.loads(_bale_files["dataset_manifest.json"])
if (_bale_manifest.get("generator_version") != "backend-catalog-synthetic-v1"
        or _bale_manifest.get("data_kind") != "synthetic"
        or set(_bale_manifest.get("files", {})) != _bale_expected - {"dataset_manifest.json"}):
    raise ValueError("Incompatible standalone input manifest.")
for _bale_name, _bale_sha in _bale_manifest["files"].items():
    if _bale_hashlib.sha256(_bale_files[_bale_name]).hexdigest() != _bale_sha:
        raise ValueError("Input checksum mismatch: " + _bale_name)
BALE_INPUT_DIR.mkdir(exist_ok=True)
for _bale_name, _bale_data in _bale_files.items():
    (BALE_INPUT_DIR / _bale_name).write_bytes(_bale_data)
print("Verified standalone synthetic inputs:", _bale_manifest["rows"], "sale lines for", _bale_manifest["stores"], "backend stores.")
'''


def configured_notebook(canonical_path, output):
    notebook = json.loads(Path(canonical_path).read_text(encoding="utf-8"))
    notebook = copy.deepcopy(notebook)
    notebook["cells"][0]["source"] = """# BALE existing-store demo: ready for Google Colab

1. Choose **Runtime > Run all** on a CPU runtime.
2. When prompted, select **Bale_Backend_Demo_Inputs.zip** from your computer.
3. Wait for training, evaluation, and export. The results ZIP downloads at the end.

Uses existing backend store/catalog IDs with **synthetic** sales and reporting evidence.
The input ZIP contains no backend credentials or user profiles. No database connection
is needed. The feature/training/evaluation functions are unchanged from the canonical
Panabo notebook. Category quantities count sellable variant packages/items, not kg/mL.
Only the exported stores' actual barangays are represented. Backend identity/unit
mappings are supplied locally in backend_mappings.json for the later import step.
"""
    configuration = next(cell for cell in notebook["cells"] if "config" in cell.get("metadata", {}).get("tags", []))
    source = "".join(configuration["source"])
    replacements = {"DEMO_PRESET": "None", "MODE": '"train"', "CSV_PATH": 'BALE_INPUT_DIR / "transactions.csv"',
                    "COVERAGE_PATH": 'BALE_INPUT_DIR / "coverage.csv"', "GENERATE_DEMO": "False", "DATA_KIND": '"synthetic"',
                    "AS_OF": '_bale_manifest["as_of"]', "FORECAST_CUTOFF": '_bale_manifest["end"]',
                    "COORDINATES_PATH": 'BALE_INPUT_DIR / "areas.csv"',
                    "CATEGORY_LABELS": 'pd.read_csv(BALE_INPUT_DIR / "categories.csv", dtype="string").set_index("category_id")["label"].to_dict()',
                    "AREA_REGISTRY": 'pd.read_csv(BALE_INPUT_DIR / "areas.csv", dtype="string")[["city", "barangay", "area_id"]].to_dict("records")'}
    for name, expression in replacements.items():
        source, count = re.subn(r"^" + name + r"\s*=.*$", name + " = " + expression, source, count=1, flags=re.MULTILINE)
        if count != 1:
            raise ValueError("Canonical notebook config changed: " + name)
    configuration["source"] = source
    config_index = notebook["cells"].index(configuration)
    notebook["cells"].insert(config_index, {"cell_type": "code", "execution_count": None, "id": "backend-input-upload",
        "metadata": {"tags": ["backend-input-loader"]}, "outputs": [], "source": INPUT_LOADER})
    notebook["cells"].append({"cell_type": "code", "execution_count": None, "id": "backend-result-download", "metadata": {}, "outputs": [],
        "source": 'try:\n    from google.colab import files as _bale_results_files\nexcept ImportError:\n    print("Results ZIP:", zip_path)\nelse:\n    _bale_results_files.download(str(zip_path))\n'})
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            cell["outputs"], cell["execution_count"] = [], None
            compile("".join(cell["source"]), cell.get("id", "cell"), "exec")
    notebook["metadata"]["bale_canonical_notebook_sha256"] = panabo_sha256(canonical_path)
    Path(output).write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def prepare(catalog, output, **kwargs):
    manifest = generate_inputs(catalog, output, **kwargs)
    configured_notebook(ROOT / "Panabo_Area_Demand_Forecastingg.ipynb", Path(output) / NOTEBOOK_NAME)
    instructions = f"""# Ready-to-run standalone Colab handoff

No sales were inserted into PostgreSQL. Existing store/catalog IDs came from
the local catalog snapshot; every generated sale and coverage record is synthetic.

## Do this now

1. Open Google Colab and choose File > Upload notebook.
2. Select {NOTEBOOK_NAME} from this folder.
3. Choose Runtime > Run all, using a CPU runtime.
4. When prompted by the notebook, select {ZIP_NAME}.
5. Wait for training and save the results ZIP downloaded at the end.

No settings need editing. Keep this input ZIP separate from the training-results ZIP.
If the automatic download is blocked, download the printed ml_outputs/<run_id>.zip
from Colab's Files panel. Return with that results ZIP for the backend import step.

## Input profile

- {manifest['rows']:,} synthetic completed sale lines across {manifest['stores']} existing backend stores.
- {manifest['variants']} variants, {manifest['categories']} categories, {manifest['areas']} actual store barangays.
- {manifest['days']} dates: {manifest['start']} through {manifest['end']}.
- {manifest['row_counts']['coverage.csv']:,} simulated complete-reporting statements.
- Forecast dates: {manifest['forecast_start']} through {manifest['forecast_end']}.
- One sellable_unit is one variant package/item, including multi-packs as one sale unit.
- Package contents are not converted. Category totals can mix package sizes.

backend_mappings.json stays local for later registration in the existing bale
database's forecast module. It creates no users, stores, products, orders or sales.
The original notebook is unchanged. No model has been trained by this preparation.
"""
    (Path(output) / "START_HERE.md").write_text(instructions, encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "inputs/backend_catalog.json")
    parser.add_argument("--output", type=Path, default=ROOT / "colab_handoff/backend_catalog_demo")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--rows", type=int, default=50000)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    manifest = prepare(args.catalog, args.output, days=args.days, rows=args.rows, end_date=args.end_date, seed=args.seed)
    print(json.dumps({"output": str(args.output), "stores": manifest["stores"], "rows": manifest["rows"],
                      "coverage_rows": manifest["row_counts"]["coverage.csv"], "forecast_start": manifest["forecast_start"],
                      "forecast_end": manifest["forecast_end"], "sales_inserted_in_database": 0}, indent=2))


if __name__ == "__main__":
    main()
