"""Generate one deliberately messy input ZIP for the unchanged backend notebook.

No database access, notebook generation, or changes to existing datasets.
Run: python scripts/generate_messy_backend.py
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import random
import zipfile

from generate_panabo import PANABO_COLUMNS, PANABO_TZ, panabo_sha256, panabo_write_csv
from prepare_backend_colab import ROOT, UNIT, VERSION, load_catalog

ZIP_NAME = "Bale_Backend_Messy_Inputs.zip"
BASE_ROWS = 49690
EXPECTED_AUDIT = {"input_rows":50000, "accepted_completed_rows":49656,
                  "excluded_status_rows":150, "exact_duplicates_removed":150,
                  "quarantined_rows":44, "global_block":False}


def generate_messy(catalog_path, directory, *, end_date="2026-11-08", seed=None, profile="original"):
    if seed is None:
        seed = 20261110 if profile == "forty_stores_behavior_v2" else 20261109
    if profile in {"forty_stores", "forty_stores_behavior_v2"}:
        from messy_forty_stores import generate_forty_stores
        return generate_forty_stores(catalog_path, directory, end_date=end_date, seed=seed,
                                    behavior_v2=profile == "forty_stores_behavior_v2")
    if profile != "original":
        raise ValueError("Unknown messy-data profile.")
    end = date.fromisoformat(str(end_date))
    if end >= datetime.now(PANABO_TZ).date():
        raise ValueError("Synthetic history must end before the current Manila day.")
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError(f"Refusing to overwrite an existing dataset: {directory}")
    reference = json.loads((ROOT / "data/panabo_reference.json").read_text(encoding="utf-8"))
    stores, categories, variants, groups, areas = load_catalog(catalog_path, reference)
    distinct = {}
    for key in groups:
        distinct.setdefault((stores[key[0]]["area_id"], key[1]), key)
    if len(distinct) < 3:
        raise ValueError("The messy profile needs at least three distinct area/category combinations.")
    corrupt_group, partial_group, late_group = list(distinct.values())[:3]
    corrupt_area = (stores[corrupt_group[0]]["area_id"], corrupt_group[1])
    start = end - timedelta(days=179)
    dates = [start + timedelta(days=i) for i in range(180)]
    rng = random.Random(seed)
    slots, weights, parameters = [], [], []
    for key in groups:
        level, trend = rng.uniform(.65, 1.6), rng.uniform(-.2, .3)
        weekday = [rng.uniform(.8, 1.2) for _ in range(5)] + [rng.uniform(.7, 1.5) for _ in range(2)]
        zero_probability = rng.uniform(.08, .18)
        parameters.append({"store_id":key[0], "category_id":key[1], "relative_activity":level,
                           "weekday_weights":weekday, "history_trend":trend,
                           "zero_activity_probability":zero_probability})
        for i, observed in enumerate(dates):
            weight = level * weekday[observed.weekday()] * (1 + trend*i/179) * rng.lognormvariate(0, .25)
            if rng.random() < zero_probability:
                weight = 0.
            slots.append((key, observed))
            weights.append(weight)
    # Fixed total is a disclosed demonstration budget, not an activity floor.
    counts = Counter(rng.choices(range(len(slots)), weights=weights, k=BASE_ROWS))
    base, coverage = [], []
    late_dates = {end-timedelta(days=84), end-timedelta(days=70)}
    bulk_ids = []
    for index, (key, observed) in enumerate(slots):
        store_id, category_id = key
        store = stores[store_id]
        delay = 2 if key == late_group and observed in late_dates else 1
        known = datetime.combine(observed+timedelta(days=delay), time(0, 5), PANABO_TZ).isoformat()
        coverage.append({"store_id":store_id, "city":store["city"], "barangay":store["barangay"],
                         "category_id":category_id, "date":observed.isoformat(),
                         "participation_status":"active",
                         "reporting_status":"partial" if key == partial_group and observed == end else "complete",
                         "operating_status":"open", "availability_status":"unknown",
                         "known_at":known, "coverage_source":"backend-messy-hypothetical-v1"})
        for line in range(counts[index]):
            variant = rng.choice(groups[key])
            quantity = max(1, min(12, int(round(rng.gammavariate(1.8, .8)))))
            identity = f"messy-synthetic:{observed}:{store_id}:{category_id}:{line+1}"
            if rng.random() < .003:
                quantity = rng.randint(8, 20)
                bulk_ids.append(identity+":line:1")
            event = datetime.combine(observed, time(8), PANABO_TZ) + timedelta(seconds=rng.randrange(14*3600))
            base.append(dict(zip(PANABO_COLUMNS, map(str, [event.isoformat(), known, identity, identity+":line:1",
                "completed", store_id, store["city"], store["barangay"], variant["product_id"], variant["variant_id"],
                category_id, quantity, UNIT, "online" if rng.random() < .18 else "pos"]))))
    candidates = [i for i, row in enumerate(base) if (row["store_id"], row["category_id"]) == corrupt_group
                  and date.fromisoformat(row["transaction_datetime"][:10]) >= end-timedelta(days=6)]
    if len(candidates) < 34:
        raise ValueError("Not enough final-week records in the selected corruption combination.")
    chosen = rng.sample(candidates, 34)
    quantity_indexes, product_indexes, status_indexes, conflict_indexes = chosen[:12], chosen[12:18], chosen[18:24], chosen[24:]
    invalid_quantities = ["0", "-2", "not_recorded", "inf"] * 3
    for i, value in zip(quantity_indexes, invalid_quantities):
        base[i]["quantity"] = value
    for i in product_indexes:
        base[i]["product_id"] = ""
    for i in status_indexes:
        base[i]["transaction_status"] = "pending_review"
    excluded = set(chosen)
    clean_indexes = [i for i in range(len(base)) if i not in excluded]
    formatted = rng.sample(clean_indexes, 400)
    for i in formatted:
        row = base[i]
        row["city"] = " Panabo City "
        row["barangay"] = " BRGY. " + row["barangay"].upper() + " "
        row["unit_label"] = " SELLABLE_UNIT "
        row["sales_channel"] = " " + row["sales_channel"].upper() + " "
    duplicate_indexes = rng.sample(clean_indexes, 150)
    sales = [dict(row) for row in base]
    sales += [dict(base[i]) for i in duplicate_indexes]
    for i in conflict_indexes:
        row = dict(base[i])
        row["quantity"] = str(int(row["quantity"]) + 7)
        sales.append(row)
    for number, i in enumerate(rng.sample(clean_indexes, 150)):
        row = dict(base[i])
        status = "cancelled" if number < 100 else "voided"
        row["transaction_id"] += f":{status}:{number}"
        row["transaction_item_id"] += f":{status}:{number}"
        row["transaction_status"] = status
        sales.append(row)
    rng.shuffle(sales)
    assert len(sales) == 50000

    # These are the cleaned, deduplicated completed sales, before group withholding.
    accepted = [row for i, row in enumerate(base) if i not in excluded]
    totals = Counter()
    for row in accepted:
        totals[(row["store_id"], row["category_id"], row["transaction_datetime"][:10])] += int(row["quantity"])
    store_daily, area_totals, area_complete = [], Counter(), {}
    for row in coverage:
        key = (row["store_id"], row["category_id"])
        area = stores[key[0]]["area_id"]
        complete = key != corrupt_group and row["reporting_status"] == "complete"
        sold = totals[(key[0], key[1], row["date"])]
        area_key = (area, key[1], row["date"])
        area_totals[area_key] += sold
        area_complete[area_key] = area_complete.get(area_key, True) and complete
        store_daily.append({"store_id":key[0], "area_id":area, "category_id":key[1], "date":row["date"],
                            "units_sold":sold if complete else "",
                            "observation_status":"complete" if complete else "incomplete_reporting", "data_kind":"synthetic"})
    area_daily = [{"area_id":a, "category_id":c, "date":d,
                   "units_sold":q if area_complete[(a,c,d)] else "",
                   "observation_status":"complete" if area_complete[(a,c,d)] else "incomplete_reporting",
                   "data_kind":"synthetic"} for (a,c,d),q in sorted(area_totals.items())]
    category_rows = [{"category_id":k, "label":v, "unit_label":UNIT, "unit_policy":"recorded_sale_units"}
                     for k,v in sorted(categories.items(), key=lambda p:int(p[0]))]
    products = [{k:row.get(k, "") for k in ["store_id", "product_id", "product_name", "variant_id", "category_id", "sku", "package_description"]}
                | {"unit_label":UNIT} for row in sorted(variants.values(), key=lambda r:int(r["variant_id"]))]
    daily_columns = ["area_id", "category_id", "date", "units_sold", "observation_status", "data_kind"]
    tables = {"transactions.csv":(PANABO_COLUMNS, sales), "coverage.csv":(list(coverage[0]),coverage),
              "areas.csv":(["area_id", "city", "barangay", "latitude", "longitude", "coordinate_source"],areas),
              "stores.csv":(list(next(iter(stores.values()))),list(stores.values())),
              "categories.csv":(list(category_rows[0]),category_rows), "products.csv":(list(products[0]),products),
              "store_daily_observations.csv":(["store_id", *daily_columns],store_daily),
              "area_daily_observations.csv":(daily_columns,area_daily)}
    scenarios = {
        "corrupt_store_category":list(corrupt_group), "corrupt_area_category":list(corrupt_area),
        "partial_store_category":list(partial_group), "partial_reporting_date":end.isoformat(),
        "late_store_category":list(late_group), "late_reporting_dates":[d.isoformat() for d in sorted(late_dates)],
        "reporting_delay":"Normally next day 00:05 Manila; selected late days arrive two days after the event at 00:05.",
        "formatting_rows":400, "exact_duplicate_copies":150, "cancelled_rows":100, "voided_rows":50,
        "invalid_quantity_rows":12, "missing_product_id_rows":6, "unsupported_status_rows":6,
        "conflicting_pairs":10, "bulk_purchase_source_rows":len(bulk_ids),
        "conflict_item_ids":[base[i]["transaction_item_id"] for i in conflict_indexes],
        "invalid_quantity_item_ids":[base[i]["transaction_item_id"] for i in quantity_indexes],
        "missing_product_item_ids":[base[i]["transaction_item_id"] for i in product_indexes],
        "unsupported_status_item_ids":[base[i]["transaction_item_id"] for i in status_indexes],
        "expected_cleaning_audit":EXPECTED_AUDIT,
        "expected_withholding":"Invalid/conflicting records withhold one combination; partial latest reporting withholds a second. Other combinations remain subject to normal eligibility checks.",
        "parameters":parameters,
    }
    assumptions = [
        "All sales, quantities and reporting statements are invented; backend catalog identities are reused. No database is read or modified by this script.",
        "Store/category activity and weekday weights vary; daily noise and gradual -20% to +30% changes are hypothetical assumptions, not measured local behavior.",
        "Some days have no activity. There is no forced sale every four dates. The total sale-line budget is fixed for comparison with the earlier demo.",
        "About 0.3% of base sale lines are deliberately large valid purchases; quantities still count sellable packages/items, not kg or mL.",
        "Partial reporting remains unknown rather than zero. Supplemental observations match the current cleaned/withheld snapshot, not a sum of raw dirty transactions.",
        "The current notebook quarantines records conservatively: an affected combination may be withheld even though it has many other valid sales.",
        "Synthetic scores demonstrate workflow behavior and do not establish real predictive accuracy. No model is selected in advance to win.",
    ]
    manifest = {"schema_version":"market-demand-v1", "generator_version":VERSION,
        "generation_profile":"messy-hypothetical-v1", "data_kind":"synthetic", "seed":seed,
        "source_catalog_sha256":panabo_sha256(catalog_path), "days":180, "rows":len(sales),
        "start":start.isoformat(), "end":end.isoformat(),
        "as_of":datetime.combine(end+timedelta(days=1),time(0,15),PANABO_TZ).isoformat(),
        "forecast_start":(end+timedelta(days=1)).isoformat(), "forecast_end":(end+timedelta(days=7)).isoformat(),
        "stores":len(stores), "areas":len(areas), "categories":len(categories), "variants":len(variants),
        "store_category_groups":len(groups), "area_category_groups":len(distinct),
        "recorded_units":sum(int(row["quantity"]) for row in accepted),
        "recorded_units_definition":"Accepted, deduplicated completed-sale units before group withholding; never sum the raw dirty quantity column.",
        "row_counts":{name:len(records) for name,(_,records) in tables.items()},
        "assumptions":assumptions, "intentional_scenarios":scenarios}
    directory.mkdir(parents=True, exist_ok=False)
    for name,(columns,records) in tables.items():
        panabo_write_csv(directory/name, columns, [{k:row.get(k, "") for k in columns} for row in records])
    manifest["files"] = {name:panabo_sha256(directory/name) for name in sorted(tables)}
    (directory/"dataset_manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    # Fixed member timestamps make the ZIP itself reproducible, not just its CSVs.
    with zipfile.ZipFile(directory/ZIP_NAME,"w",zipfile.ZIP_DEFLATED) as archive:
        for name in [*sorted(tables),"dataset_manifest.json"]:
            info = zipfile.ZipInfo(name, date_time=(2026,1,1,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info,(directory/name).read_bytes())
    (directory/"READ_ME_FIRST.md").write_text(instructions(manifest),encoding="utf-8")
    return manifest


def instructions(manifest):
    s = manifest["intentional_scenarios"]
    return f"""# Messy hypothetical sales: use your existing notebook

Upload **{ZIP_NAME}** when **Bale_Backend_Demo_Colab.ipynb** asks for its input ZIP.
Use a fresh Colab runtime (Disconnect and delete runtime, then reconnect) so an old
Bale_Backend_Demo_Inputs.zip is not selected automatically. Do not upload the results ZIP.
No notebook changes are needed. This folder contains no newly generated notebook.

## What you should see

- Exactly 50,000 sale lines, covering {manifest['start']} through {manifest['end']}.
- 150 duplicate copies removed; 150 cancelled/voided lines excluded.
- 44 quarantined records: 12 invalid quantities, six missing product IDs, six
  unsupported statuses, and both records in each of 10 conflicting pairs.
- 49,656 accepted completed-sale lines. The expected global block is false.
- 400 original valid rows contain accepted formatting variations. Extra spaces,
  uppercase labels and BRGY. prefixes should normalize to the existing names.
- One corrupted combination: store/category {s['corrupt_store_category']}; its
  affected area/category is {s['corrupt_area_category']}. These records have valid
  locations so they should withhold this combination, not stop the whole run.
- Store/category {s['partial_store_category']} has partial reporting on
  {s['partial_reporting_date']}; its current forecast should be withheld.
- Store/category {s['late_store_category']} reports two historical dates late:
  {', '.join(s['late_reporting_dates'])}. Earlier forecast cutoffs must not see
  those sales or completeness statements prematurely. Eligible counts can vary.
- Other combinations still need to pass the unchanged notebook's eligibility rules.

Rows are shuffled. Sales patterns vary by store/category, including genuine zero
days, gradual changes and occasional bulk purchases. No model is forced to win.
Read the exported quarantine and cleaning files alongside the notebook explanation.
Accepted sale lines are not the same as forecastable groups or forecast rows.

## Why this is synthetic

Real backend catalog identities are reused, but all sale quantities and reporting
statements are invented. Package/item units are not converted into common weights
or volumes. Results test data cleaning and forecasting behavior; they do not prove
real business accuracy. Full scenario details are in dataset_manifest.json inside
the ZIP. Do not add or remove ZIP members without updating the notebook contract.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog",type=Path,default=ROOT/"inputs/backend_catalog.json")
    parser.add_argument("--output",type=Path,default=None)
    parser.add_argument("--profile",choices=["original","forty_stores","forty_stores_behavior_v2"],default="original")
    parser.add_argument("--end-date",default="2026-11-08")
    parser.add_argument("--seed",type=int,default=None)
    args = parser.parse_args()
    folders = {"original":"backend_catalog_messy_demo", "forty_stores":"backend_catalog_messy_40_stores",
               "forty_stores_behavior_v2":"backend_catalog_messy_40_stores_behavior_v2"}
    output = args.output or ROOT/"colab_handoff"/folders[args.profile]
    manifest = generate_messy(args.catalog,output,end_date=args.end_date,seed=args.seed,profile=args.profile)
    zip_name = {"original":ZIP_NAME,"forty_stores":"Bale_Backend_Messy_40_Stores_Inputs.zip",
                "forty_stores_behavior_v2":"Bale_Backend_Messy_40_Stores_Behavior_V2_Inputs.zip"}[args.profile]
    print(json.dumps({"zip":str(output/zip_name), "rows":manifest["rows"],
                      "expected_cleaning_audit":manifest["intentional_scenarios"]["expected_cleaning_audit"]},indent=2))


if __name__ == "__main__":
    main()
