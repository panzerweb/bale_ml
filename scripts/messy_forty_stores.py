"""Forty-store extension of the messy ZIP profile; the original profile is unchanged."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import random
import zipfile

from generate_panabo import PANABO_COLUMNS, PANABO_TZ, panabo_sha256, panabo_write_csv
from prepare_backend_colab import ROOT, UNIT, VERSION, load_catalog

ZIP_NAME = "Bale_Backend_Messy_40_Stores_Inputs.zip"
EXPECTED_AUDIT = {"input_rows":200000, "accepted_completed_rows":198624,
                  "excluded_status_rows":600, "exact_duplicates_removed":600,
                  "quarantined_rows":176, "global_block":False}


def expanded_catalog(catalog_path, reference):
    stores, categories, variants, groups, original_areas = load_catalog(catalog_path, reference)
    if len(stores) != 3 or len(categories) != 7:
        raise ValueError("The forty-store profile requires the three-store, seven-category catalog.")
    selected = {a["area_id"] for a in original_areas}
    if len(selected) != 3:
        raise ValueError("The three original stores must occupy three different barangays.")
    for area in sorted(reference["areas"],key=lambda a:a["area_id"]):
        if len(selected) == 10:
            break
        selected.add(area["area_id"])
    areas = [dict(a) for a in sorted(reference["areas"],key=lambda a:a["area_id"]) if a["area_id"] in selected]
    if len(areas) != 10:
        raise ValueError("Not enough reference barangays for the forty-store profile.")
    templates = {c:sorted([v for v in variants.values() if v["category_id"] == c],
                         key=lambda v:int(v["variant_id"]))[:2] for c in categories}
    if any(len(rows) != 2 for rows in templates.values()):
        raise ValueError("Every category needs at least two existing variant templates.")
    original_ids = sorted(stores,key=int)
    used = {"store":set(stores),"product":{v["product_id"] for v in variants.values()},"variant":set(variants)}
    next_id = {key:1000000000 for key in used}
    def allocate(kind):
        while str(next_id[kind]) in used[kind]:
            next_id[kind] += 1
        result = str(next_id[kind])
        used[kind].add(result)
        next_id[kind] += 1
        return result
    fictional_ids = []
    for area in areas:
        members = [s for s in stores.values() if s["area_id"] == area["area_id"]]
        for _ in range(4-len(members)):
            store_id = allocate("store")
            fictional_ids.append(store_id)
            name = f"Fictional Store {len(fictional_ids):02d} - {area['barangay']}"
            stores[store_id] = {"store_id":store_id,"store_name":name,"area_id":area["area_id"],
                                "city":area["city"],"barangay":area["barangay"]}
            product_ids = {}
            for category in sorted(categories,key=int):
                for template in templates[category]:
                    source_product = template["product_id"]
                    if source_product not in product_ids:
                        product_ids[source_product] = allocate("product")
                    row = dict(template)
                    row.update(store_id=store_id,store_name=name,city=area["city"],barangay=area["barangay"],
                               product_id=product_ids[source_product],variant_id=allocate("variant"))
                    row["sku"] = f"SIM-{store_id}-{row['variant_id']}"
                    variants[row["variant_id"]] = row
                    groups.setdefault((store_id,category),[]).append(row)
    assert len(stores) == 40 and len(fictional_ids) == 37
    groups = dict(sorted(groups.items(),key=lambda p:tuple(map(int,p[0]))))
    return stores,categories,variants,groups,areas,original_ids,fictional_ids


def generate_forty_stores(catalog_path, directory, *, end_date="2026-11-08", seed=20261109, behavior_v2=False):
    end = date.fromisoformat(str(end_date))
    if end >= datetime.now(PANABO_TZ).date():
        raise ValueError("History must end before the current Manila day.")
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError(f"Refusing to overwrite an existing dataset: {directory}")
    reference = json.loads((ROOT/"data/panabo_reference.json").read_text(encoding="utf-8"))
    stores,categories,variants,groups,areas,original_ids,fictional_ids = expanded_catalog(catalog_path,reference)
    by_area = defaultdict(list)
    for key in groups:
        by_area[stores[key[0]]["area_id"]].append(key)
    area_ids = [a["area_id"] for a in areas]
    def choose(area, category_index, last=False):
        category = sorted(categories,key=int)[category_index]
        eligible = [key for key in by_area[area] if key[1] == category]
        return eligible[-1] if last else eligible[0]
    corrupt = [choose(a,0) for a in area_ids[:4]]
    partial = [choose(a,1) for a in area_ids[4:8]]
    late = [choose(a,2,last=True) for a in area_ids[:4]]
    if behavior_v2:
        from forty_store_behaviors import PROFILE, ZIP_NAME as BEHAVIOR_ZIP, assign_behaviors, behavior_documentation, weight_multiplier
        corrupt = [choose(a,3,last=True) for a in area_ids[3:7]]
        partial = [choose(a,4,last=True) for a in area_ids[7:]+area_ids[:1]]
        late = [choose(a,5,last=True) for a in area_ids[1:5]]
        behaviors = assign_behaviors(groups,set(corrupt+partial+late),end,seed)
    start = end-timedelta(days=179)
    dates = [start+timedelta(days=i) for i in range(180)]
    late_dates = {end-timedelta(days=84),end-timedelta(days=70)}
    if behavior_v2:
        late_dates = {end-timedelta(days=77),end-timedelta(days=63)}
    rng = random.Random(seed)
    slots,weights,parameters = [],[],[]
    for key in groups:
        level,trend = rng.uniform(.65,1.6),rng.uniform(-.2,.3)
        weekday = [rng.uniform(.8,1.2) for _ in range(5)] + [rng.uniform(.7,1.5) for _ in range(2)]
        zero_probability = rng.uniform(.08,.18)
        event = behaviors.get(key) if behavior_v2 else None
        if event and event["behavior"] == "intermittent":
            zero_probability = 1-event["active_day_probability"]
        parameters.append({"store_id":key[0],"category_id":key[1],"relative_activity":level,
                           "weekday_weights":weekday,"history_trend":trend,"zero_activity_probability":zero_probability})
        for i,day in enumerate(dates):
            weight = level*weekday[day.weekday()]*(1+trend*i/179)*rng.lognormvariate(0,.25)
            if behavior_v2:
                weight *= weight_multiplier(event,day)
            if rng.random() < zero_probability:
                weight = 0.
            slots.append((key,day))
            weights.append(weight)
    counts = Counter(rng.choices(range(len(slots)),weights=weights,k=198760))
    base,coverage = [],[]
    bulk_count = 0
    group_indexes = defaultdict(list)
    for index,(key,day) in enumerate(slots):
        store_id,category = key
        store = stores[store_id]
        delay = 2 if key in late and day in late_dates else 1
        known = datetime.combine(day+timedelta(days=delay),time(0,5),PANABO_TZ).isoformat()
        coverage.append({"store_id":store_id,"city":store["city"],"barangay":store["barangay"],
            "category_id":category,"date":day.isoformat(),"participation_status":"active",
            "reporting_status":"partial" if key in partial and day == end else "complete",
            "operating_status":"open","availability_status":"unknown","known_at":known,
            "coverage_source":PROFILE if behavior_v2 else "messy-forty-stores-v1"})
        for line in range(counts[index]):
            variant = rng.choice(groups[key])
            quantity = max(1,min(12,int(round(rng.gammavariate(1.8,.8)))))
            if rng.random() < .003:
                quantity = rng.randint(8,20)
                bulk_count += 1
            identity = f"messy40:{day}:{store_id}:{category}:{line+1}"
            if behavior_v2:
                identity = f"messy40b:{seed}:{day}:{store_id}:{category}:{line+1}"
            event = datetime.combine(day,time(8),PANABO_TZ)+timedelta(seconds=rng.randrange(14*3600))
            group_indexes[key].append(len(base))
            base.append(dict(zip(PANABO_COLUMNS,map(str,[event.isoformat(),known,identity,identity+":line:1",
                "completed",store_id,store["city"],store["barangay"],variant["product_id"],variant["variant_id"],
                category,quantity,UNIT,"online" if rng.random()<.18 else "pos"]))))
    quantity_indexes,product_indexes,status_indexes,conflict_indexes = [],[],[],[]
    for key in corrupt:
        candidates = [i for i in group_indexes[key] if date.fromisoformat(base[i]["transaction_datetime"][:10]) >= end-timedelta(days=27)]
        if len(candidates) < 34:
            candidates = group_indexes[key]
        if len(candidates) < 34:
            raise ValueError(f"Not enough source records for controlled corruption in {key}.")
        chosen = rng.sample(candidates,34)
        quantity_indexes.extend(chosen[:12]); product_indexes.extend(chosen[12:18])
        status_indexes.extend(chosen[18:24]); conflict_indexes.extend(chosen[24:])
    for i,value in zip(quantity_indexes,["0","-2","not_recorded","inf"]*12):
        base[i]["quantity"] = value
    for i in product_indexes:
        base[i]["product_id"] = ""
    for i in status_indexes:
        base[i]["transaction_status"] = "pending_review"
    excluded = set(quantity_indexes+product_indexes+status_indexes+conflict_indexes)
    clean = [i for i in range(len(base)) if i not in excluded]
    for i in rng.sample(clean,1600):
        base[i].update(city=" Panabo City ",barangay=" BRGY. "+base[i]["barangay"].upper()+" ",
                       unit_label=" SELLABLE_UNIT ",sales_channel=" "+base[i]["sales_channel"].upper()+" ")
    sales = [dict(row) for row in base]+[dict(base[i]) for i in rng.sample(clean,600)]
    for i in conflict_indexes:
        row = dict(base[i]); row["quantity"] = str(int(row["quantity"])+7); sales.append(row)
    for number,i in enumerate(rng.sample(clean,600)):
        row = dict(base[i]); status = "cancelled" if number<400 else "voided"
        row["transaction_status"] = status
        row["transaction_id"] += f":{status}:{number}"
        row["transaction_item_id"] += f":{status}:{number}"
        sales.append(row)
    rng.shuffle(sales)
    assert len(sales) == 200000
    accepted = [row for i,row in enumerate(base) if i not in excluded]
    totals = Counter()
    for row in accepted:
        totals[(row["store_id"],row["category_id"],row["transaction_datetime"][:10])] += int(row["quantity"])
    store_daily,area_totals,area_complete = [],Counter(),{}
    for row in coverage:
        key = (row["store_id"],row["category_id"])
        area = stores[key[0]]["area_id"]
        complete = key not in corrupt and row["reporting_status"] == "complete"
        sold = totals[(key[0],key[1],row["date"])]
        area_key = (area,key[1],row["date"])
        area_totals[area_key] += sold
        area_complete[area_key] = area_complete.get(area_key,True) and complete
        store_daily.append({"store_id":key[0],"area_id":area,"category_id":key[1],"date":row["date"],
            "units_sold":sold if complete else "","observation_status":"complete" if complete else "incomplete_reporting","data_kind":"synthetic"})
    area_daily = [{"area_id":a,"category_id":c,"date":d,"units_sold":q if area_complete[(a,c,d)] else "",
        "observation_status":"complete" if area_complete[(a,c,d)] else "incomplete_reporting","data_kind":"synthetic"}
        for (a,c,d),q in sorted(area_totals.items())]
    category_rows = [{"category_id":c,"label":label,"unit_label":UNIT,"unit_policy":"recorded_sale_units"}
                     for c,label in sorted(categories.items(),key=lambda p:int(p[0]))]
    products = [{k:row.get(k,"") for k in ["store_id","product_id","product_name","variant_id","category_id","sku","package_description"]}
        | {"unit_label":UNIT} for row in sorted(variants.values(),key=lambda r:int(r["variant_id"]))]
    daily_columns = ["area_id","category_id","date","units_sold","observation_status","data_kind"]
    tables = {"transactions.csv":(PANABO_COLUMNS,sales),"coverage.csv":(list(coverage[0]),coverage),
        "areas.csv":(["area_id","city","barangay","latitude","longitude","coordinate_source"],areas),
        "stores.csv":(list(next(iter(stores.values()))),list(stores.values())),
        "categories.csv":(list(category_rows[0]),category_rows),"products.csv":(list(products[0]),products),
        "store_daily_observations.csv":(["store_id",*daily_columns],store_daily),"area_daily_observations.csv":(daily_columns,area_daily)}
    def describe(key):
        s = stores[key[0]]
        return {"store_id":key[0],"area_id":s["area_id"],"barangay":s["barangay"],
                "category_id":key[1],"category_name":categories[key[1]]}
    scenarios = {"corrupt_store_categories":[describe(k) for k in corrupt],
        "partial_store_categories":[describe(k) for k in partial],"partial_reporting_date":end.isoformat(),
        "late_store_categories":[describe(k) for k in late],"late_reporting_dates":[d.isoformat() for d in sorted(late_dates)],
        "reporting_delay":"Normally next day 00:05 Manila; selected reports and sales arrive two days after the event at 00:05.",
        "formatting_rows":1600,"exact_duplicate_copies":600,"cancelled_rows":400,"voided_rows":200,
        "invalid_quantity_rows":48,"missing_product_id_rows":24,"unsupported_status_rows":24,"conflicting_pairs":40,
        "bulk_purchase_source_rows":bulk_count,"expected_cleaning_audit":EXPECTED_AUDIT,"parameters":parameters,
        "conflict_item_ids":[base[i]["transaction_item_id"] for i in conflict_indexes],
        "invalid_quantity_item_ids":[base[i]["transaction_item_id"] for i in quantity_indexes],
        "missing_product_item_ids":[base[i]["transaction_item_id"] for i in product_indexes],
        "unsupported_status_item_ids":[base[i]["transaction_item_id"] for i in status_indexes]}
    manifest = {"schema_version":"market-demand-v1","generator_version":VERSION,
        "generation_profile":"messy-forty-stores-v1","data_kind":"synthetic","seed":seed,
        "source_catalog_sha256":panabo_sha256(catalog_path),"days":180,"rows":len(sales),"stores":40,"areas":10,
        "categories":len(categories),"variants":len(variants),"store_category_groups":len(groups),
        "area_category_groups":len(area_totals)//180,"start":start.isoformat(),"end":end.isoformat(),
        "as_of":datetime.combine(end+timedelta(days=1),time(0,15),PANABO_TZ).isoformat(),
        "forecast_start":(end+timedelta(days=1)).isoformat(),"forecast_end":(end+timedelta(days=7)).isoformat(),
        "recorded_units":sum(int(r["quantity"]) for r in accepted),
        "recorded_units_definition":"Accepted, deduplicated completed-sale units before group withholding; do not sum raw dirty quantities.",
        "original_store_ids":original_ids,"fictional_store_ids":fictional_ids,
        "identity_policy":"Three catalog stores are preserved. The other 37 stores and their product/variant IDs are fictional, allocated from 1000000000 upward while skipping existing IDs; they are not registered backend records.",
        "assumptions":["All sales and reporting statements are hypothetical; no database is accessed or modified.",
            "Exactly four stores occupy each of ten barangays. Original product assignments are retained; fictional stores clone two variant templates in each of seven categories with new IDs.",
            "Store/category weekday weights, noise and gradual -20% to +30% changes are invented assumptions, not measured local behavior.",
            "There is no forced-sale activity floor. Some days have genuine zero sales. The 198760-line base budget is fixed for this comparison.",
            "About 0.3% of base lines are deliberately large valid purchases. Packages/items are counted without conversion to common weights or volumes.",
            "Corrupted store/category combinations are withheld; their area/category totals are also withheld. One incomplete contributing store prevents a complete area total.",
            "Supplemental observations describe the current cleaned/withheld snapshot. Historical late records enter only after their known_at time.",
            "Synthetic scores test workflow behavior, not real business accuracy. No model is forced to win."],
        "row_counts":{name:len(records) for name,(_,records) in tables.items()},"intentional_scenarios":scenarios}
    if behavior_v2:
        manifest["generation_profile"] = PROFILE
        manifest["sales_behaviors"] = {"ordinary_combinations":len(groups)-len(behaviors),
            "promotion_combinations":20,"level_shift_combinations":20,"intermittent_combinations":20,
            "events":[],"used_as_model_features":False,
            "interpretation":"Multipliers change sampling weights under a fixed total sale-line budget, not guaranteed quantity ratios."}
        accepted_counts = Counter((r["store_id"],r["category_id"],r["transaction_datetime"][:10]) for r in accepted)
        for key,event in behaviors.items():
            event_start,event_end = date.fromisoformat(event["start"]),date.fromisoformat(event["end"])
            event_counts = [accepted_counts[(key[0],key[1],day.isoformat())] for day in dates if event_start <= day <= event_end]
            manifest["sales_behaviors"]["events"].append({**describe(key),**event,
                "realized_event_sale_lines":sum(event_counts),"realized_event_active_days":sum(q>0 for q in event_counts),
                "realized_event_days":len(event_counts)})
        manifest["assumptions"].append("Version 2 adds disjoint promotion, level-shift and intermittent-activity scenarios outside cleaning/reporting targets; event labels are documentation, not predictive inputs.")
    directory.mkdir(parents=True,exist_ok=False)
    for name,(columns,records) in tables.items():
        panabo_write_csv(directory/name,columns,[{k:row.get(k,"") for k in columns} for row in records])
    manifest["files"] = {name:panabo_sha256(directory/name) for name in sorted(tables)}
    (directory/"dataset_manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    names = [*sorted(tables),"dataset_manifest.json"]
    if sum((directory/name).stat().st_size for name in names) > 100*1024*1024:
        raise ValueError("Generated input exceeds the unchanged loader's 100 MiB limit.")
    zip_name = BEHAVIOR_ZIP if behavior_v2 else ZIP_NAME
    with zipfile.ZipFile(directory/zip_name,"w",zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            info = zipfile.ZipInfo(name,date_time=(2026,1,1,0,0,0)); info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info,(directory/name).read_bytes())
    guide = instructions(manifest,zip_name=zip_name)
    if behavior_v2:
        guide += behavior_documentation(manifest)
    (directory/"READ_ME_FIRST.md").write_text(guide,encoding="utf-8")
    return manifest


def instructions(manifest, *, zip_name=ZIP_NAME):
    scenarios = manifest["intentional_scenarios"]
    def descriptions(key):
        return "\n".join(f"- {r['barangay']} / {r['category_name']} / store {r['store_id']}" for r in scenarios[key])
    return f"""# Forty-store messy dataset: use your existing notebook

Use **Bale_Backend_Demo_Colab.ipynb** without editing it. Start a fresh Colab runtime
(Disconnect and delete runtime, then reconnect), select Run all, and upload
**{zip_name}** when prompted. No new notebook is supplied or required.

## Dataset

200,000 sale lines across 40 stores, ten Panabo barangays, and seven categories.
Exactly four stores per barangay. History: {manifest['start']} through {manifest['end']}.
Forecast: {manifest['forecast_start']} through {manifest['forecast_end']}.
The three original stores remain; 37 stores have explicitly fictional identities.
Those new IDs are not registered backend records. This package is for notebook testing.

## Expected cleaning

- 600 duplicate copies removed; 400 cancelled and 200 voided lines excluded.
- 176 records set aside: 48 invalid quantities, 24 missing product IDs, 24 unknown
  statuses, and both versions of 40 conflicting sales (80 records).
- 198,624 completed-sale lines accepted; no global block.
- 1,600 source rows contain accepted formatting differences; names should normalize.
- Shuffled rows, genuine zero-sales days, different weekday patterns, gradual changes,
  and occasional bulk purchases exercise the normal forecasting workflow.

## Deliberately corrupted store/category combinations

{descriptions('corrupt_store_categories')}

These combinations have invalid/conflicting records and should be withheld. Other
stores can still have their own forecasts, but the area total for the affected
category cannot be complete, so the affected area/category forecast is withheld too.

## Partial reporting on {scenarios['partial_reporting_date']}

{descriptions('partial_store_categories')}

One contributor with unknown sales prevents a complete area/category total. Missing
sales remain unknown, not zero. Other combinations still need to pass eligibility.

## Historical reporting delays

{descriptions('late_store_categories')}

On {', '.join(scenarios['late_reporting_dates'])}, these stores' sales and reporting
statements arrive two days after the event, rather than the following morning.
Earlier forecasts cannot use them; eligible counts can change between test weeks.

All quantities and reporting statements are hypothetical. Different package sizes
are not converted into equivalent consumption. Model rankings show performance on
this generated experiment, not demonstrated accuracy on real customer sales.
Scenario details and expected counts are also inside dataset_manifest.json.
"""
