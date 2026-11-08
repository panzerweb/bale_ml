"""Build a small, explicitly illustrative export/filter/UI example. No ML training.

History and geography are copied from the existing synthetic Panabo dataset.
Future predictions are invented teaching values, not evaluated model outputs.
Run from any directory: python scripts/build_model_toggle_example.py
"""
from collections import Counter
import csv
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT/"examples/model_toggle"
INPUT = ROOT/"demo_data/panabo_50k"
METHODS = ["lightgbm", "xgboost", "random_forest"]
AREAS = ["1102315009", "1102315025"]
CATEGORIES = ["demo-beverages", "demo-snacks"]
SELECTED_STORE = "demo-panabo-1102315009-01"
SELECTED_AREA = "1102315009"
SELECTED_CATEGORY = "demo-beverages"
CUTOFF = date(2026, 11, 8)
RUN_ID = "illustrative-toggle-20261109"


def read_rows(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def write_rows(path, rows, columns=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = columns or list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def rounded(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def select_predictions(rows, method, area=None, store=None, category=None):
    """This filtering is the operation performed on a model-toggle request."""
    return sorted([
        row for row in rows
        if row["method"] == method
        and (area is None or row["area_id"] == area)
        and (store is None or row.get("store_id") == store)
        and (category is None or row["category_id"] == category)
    ], key=lambda row:(row["area_id"], row.get("store_id", ""), row["category_id"], row["forecast_date"]))


def build_view(method):
    """Read the source CSVs and construct the same view data an API could return.

    No predictions are generated here. Only filtering, matching, sums, and a
    previous-week percentage are performed. A deployed backend would query its DB.
    """
    source = OUTPUT/"source"
    metadata = json.loads((source/"run_metadata.json").read_text(encoding="utf-8"))
    store_candidates = read_rows(source/"store_candidate_future_forecasts.csv")
    area_candidates = read_rows(source/"candidate_future_forecasts.csv")
    future = select_predictions(store_candidates, method, SELECTED_AREA, SELECTED_STORE, SELECTED_CATEGORY)
    expected_dates = {(CUTOFF+timedelta(days=i)).isoformat() for i in range(1, 8)}
    if len(future) != 7 or {r["forecast_date"] for r in future} != expected_dates:
        raise ValueError("Selected store forecast does not contain seven unique expected dates")
    history = [r for r in read_rows(source/"store_historical_observations.csv")
               if r["store_id"] == SELECTED_STORE and r["area_id"] == SELECTED_AREA
               and r["category_id"] == SELECTED_CATEGORY]
    history.sort(key=lambda r:r["date"])
    previous = [r for r in history if (CUTOFF-timedelta(days=6)).isoformat() <= r["date"] <= CUTOFF.isoformat()]
    complete = len(previous) == 7 and all(r["observation_status"] == "complete" for r in previous)
    previous_units = sum(Decimal(r["units_sold"]) for r in previous) if complete else None
    total = sum(Decimal(r["predicted_units"]) for r in future)
    change = float((total/previous_units-1)*100) if previous_units is not None and previous_units > 0 else None
    areas = {r["area_id"]:r for r in read_rows(source/"area_labels.csv")}
    coordinates = {r["area_id"]:r for r in read_rows(source/"area_coordinates.csv")}
    catalog = {r["category_id"]:r for r in read_rows(source/"categories.csv")}
    stores = {r["store_id"]:r for r in read_rows(source/"stores.csv")}
    points = []
    for area_id in AREAS:
        # Barangay forecasts come from the AREA file; do not sum store models.
        area_future = select_predictions(area_candidates, method, area=area_id, category=SELECTED_CATEGORY)
        if len(area_future) != 7 or {r["forecast_date"] for r in area_future} != expected_dates:
            raise ValueError("Area forecast is incomplete")
        points.append({"area_id":area_id, "barangay":areas[area_id]["barangay"],
            "category_id":SELECTED_CATEGORY, "method":method,
            "latitude":float(coordinates[area_id]["latitude"]),
            "longitude":float(coordinates[area_id]["longitude"]),
            "coordinate_source":coordinates[area_id]["coordinate_source"],
            "total_units":float(sum(Decimal(r["predicted_units"]) for r in area_future))})
    chart = [{"date":r["date"], "actual_units":int(r["units_sold"]), "predicted_units":None,
              "horizon_day":None, "method":None} for r in history]
    chart += [{"date":r["forecast_date"], "actual_units":None,
               "predicted_units":float(r["predicted_units"]), "horizon_day":int(r["horizon_day"]),
               "method":method} for r in future]
    return {"run_id":metadata["run_id"], "data_kind":"synthetic", "forecast_kind":"illustrative_not_trained",
        "recommended_method":metadata["store_method"], "recommendation_status":metadata["recommendation_status"],
        "displayed_method":method, "scope":"store", "store_id":SELECTED_STORE,
        "store_name":stores[SELECTED_STORE]["store_name"], "area_id":SELECTED_AREA,
        "barangay":areas[SELECTED_AREA]["barangay"], "category_id":SELECTED_CATEGORY,
        "category_label":catalog[SELECTED_CATEGORY]["category_label"], "unit_label":catalog[SELECTED_CATEGORY]["unit_label"],
        "forecast_start":min(expected_dates), "forecast_end":max(expected_dates),
        "history":chart[:len(history)], "forecast":chart[len(history):],
        "summary":{"forecast_total":float(total), "previous_week_units":float(previous_units) if previous_units is not None else None,
                   "change_pct":change, "complete_history_days":sum(r["observation_status"]=="complete" for r in history)},
        "map_scope":"barangay", "map_points":points,
        "performance":{"status":"not_evaluated_example", "MAE":None, "RMSE":None, "WAPE_pct":None}}


def main():
    source = OUTPUT/"source"
    source.mkdir(parents=True, exist_ok=True)
    stores = [r for r in read_rows(INPUT/"stores.csv") if r["area_id"] in AREAS]
    categories = [r for r in read_rows(INPUT/"categories.csv") if r["category_id"] in CATEGORIES]
    areas = [r for r in read_rows(INPUT/"areas.csv") if r["area_id"] in AREAS]
    for filename, rows in [("stores.csv",stores), ("categories.csv",categories)]:
        write_rows(source/filename, rows)
    write_rows(source/"area_labels.csv", [{k:r[k] for k in ["area_id","city","barangay"]} for r in areas])
    write_rows(source/"area_coordinates.csv", [{k:r[k] for k in ["area_id","latitude","longitude","coordinate_source"]} for r in areas])
    for filename in ["store_daily_observations.csv", "area_daily_observations.csv"]:
        rows = [r for r in read_rows(INPUT/filename) if r["area_id"] in AREAS
                and r["category_id"] in CATEGORIES and r["date"] >= "2026-10-12"]
        outname = "store_historical_observations.csv" if filename.startswith("store") else "historical_observations.csv"
        write_rows(source/outname, rows)
    shapes = {
        "lightgbm":["2.1","2.8","2.4","3.2","2.5","3.4","3.6"],
        "xgboost":["3.2","3.8","3.1","4.0","3.3","3.8","3.8"],
        "random_forest":["2.6","2.7","2.5","2.9","2.6","2.8","2.9"],
    }
    store_rows, area_rows = [], []
    for method in METHODS:
        for store in stores:
            area_factor = Decimal("1") if store["area_id"] == SELECTED_AREA else Decimal("0.9")
            store_factor = Decimal("1") if store["store_id"].endswith("-01") else Decimal("1.15")
            for category in CATEGORIES:
                category_factor = Decimal("1") if category == SELECTED_CATEGORY else Decimal("0.8")
                for i, amount in enumerate(shapes[method], 1):
                    store_rows.append({"store_id":store["store_id"], "area_id":store["area_id"], "category_id":category,
                        "forecast_date":(CUTOFF+timedelta(days=i)).isoformat(), "horizon_day":i,
                        "predicted_units":str(rounded(Decimal(amount)*area_factor*store_factor*category_factor)), "method":method})
        for area in AREAS:
            for category in CATEGORIES:
                total = {"lightgbm":Decimal("44"),"xgboost":Decimal("51"),"random_forest":Decimal("43")}[method]
                total *= Decimal("1") if area == SELECTED_AREA else Decimal("0.85")
                total *= Decimal("1") if category == SELECTED_CATEGORY else Decimal("0.75")
                allocated = Decimal("0")
                for i, weight in enumerate([".12",".13",".13",".14",".14",".16",".18"], 1):
                    amount = rounded(total*Decimal(weight)) if i < 7 else total-allocated
                    allocated += amount
                    area_rows.append({"area_id":area, "category_id":category,
                        "forecast_date":(CUTOFF+timedelta(days=i)).isoformat(), "horizon_day":i,
                        "predicted_units":str(rounded(amount)), "method":method})
    write_rows(source/"store_candidate_future_forecasts.csv", store_rows)
    write_rows(source/"candidate_future_forecasts.csv", area_rows)
    # Like the real exports, recommended forecast CSVs get their method from metadata.
    for filename, rows in [("store_daily_future_forecast.csv",store_rows),("daily_future_forecast.csv",area_rows)]:
        write_rows(source/filename,[{**{k:v for k,v in r.items() if k!="method"},
            "run_id":RUN_ID,"unit_policy":"recorded_sale_units"} for r in rows if r["method"]=="lightgbm"])
    comparison = [{"method":m,"MAE":"","RMSE":"","bias":"","WAPE_pct":"","rows":0,
                   "status":"not_evaluated_example"} for m in METHODS]
    for filename in ["model_comparison.csv","store_model_comparison.csv"]:
        write_rows(source/filename, comparison)
    metadata = {"run_id":RUN_ID,"data_kind":"synthetic","forecast_kind":"illustrative_not_trained",
        "method":"lightgbm","store_method":"lightgbm","recommendation_status":"illustrative_default_not_evaluated",
        "forecast_cutoff":CUTOFF.isoformat(),"forecast_start":"2026-11-09","forecast_end":"2026-11-15",
        "forecast_days":7,"unit_policy":"recorded_sale_units",
        "notice":"Teaching fixture only. Future values and recommendation are illustrative, not trained/evaluated forecasts. This is not a complete production import bundle.",
        "source_history":"demo_data/panabo_50k: existing synthetic history and sourced geography",
        "artifacts":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source.glob("*.csv"))}}
    write_json(source/"run_metadata.json", metadata)
    stages = [("01_all_models_all_stores.csv",store_rows),
        ("02_xgboost_all_stores.csv",select_predictions(store_rows,"xgboost")),
        ("03_xgboost_gredu.csv",select_predictions(store_rows,"xgboost",area=SELECTED_AREA)),
        ("04_xgboost_gredu_store1_all_categories.csv",select_predictions(store_rows,"xgboost",SELECTED_AREA,SELECTED_STORE))]
    counts = [{"file":name,"rows":len(rows)} for name,rows in stages]
    for filename, rows in stages:
        write_rows(OUTPUT/"filtered"/filename, rows)
    summaries, preview_responses = [], {}
    for method in METHODS:
        filename=f"05_{method}_gredu_store1_beverages.csv"
        selected = select_predictions(store_rows,method,SELECTED_AREA,SELECTED_STORE,SELECTED_CATEGORY)
        write_rows(OUTPUT/"filtered"/filename, selected)
        counts.append({"file":filename,"rows":len(selected)})
        view = build_view(method)
        write_json(OUTPUT/"ui"/f"response_{method}.json",view)
        write_rows(OUTPUT/"ui"/f"chart_{method}.csv",view["history"]+view["forecast"])
        write_rows(OUTPUT/"ui"/f"map_{method}.csv",view["map_points"])
        summaries.append({"method":method,"run_id":RUN_ID,"store_id":SELECTED_STORE,"area_id":SELECTED_AREA,
            "category_id":SELECTED_CATEGORY,**view["summary"],"performance_status":view["performance"]["status"]})
        preview_responses[method]=view
    write_rows(OUTPUT/"filtered/filter_steps.csv", counts)
    write_rows(OUTPUT/"ui/summary_by_model.csv", summaries)
    payload = {"responses":preview_responses,"filter_counts":[168,56,28,14,7]}
    template = ROOT/"visualizations/model-toggle-example-template.html"
    if template.exists():
        fragment = template.read_text(encoding="utf-8").replace("__EXAMPLE_DATA_JSON__", json.dumps(payload,ensure_ascii=False).replace("<","\\u003c"))
        (ROOT/"visualizations/model-toggle-filtered-example.html").write_text(fragment,encoding="utf-8")
    manifest = {str(p.relative_to(OUTPUT).as_posix()):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(OUTPUT.rglob("*")) if p.is_file() and p.name!="example_manifest.json"}
    write_json(OUTPUT/"example_manifest.json",{"data_kind":"synthetic","forecast_kind":"illustrative_not_trained","files":manifest})
    archive = ROOT/"Model_Toggle_Filtered_Examples.zip"
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
        for p in sorted(OUTPUT.rglob("*")):
            if p.is_file():
                info=zipfile.ZipInfo("model_toggle/"+p.relative_to(OUTPUT).as_posix(),(2026,11,9,0,15,0))
                info.compress_type=zipfile.ZIP_DEFLATED
                z.writestr(info,p.read_bytes())
    print("Source store forecast rows:",len(store_rows),"| area forecast rows:",len(area_rows))
    print("Filter stages:",[(r["file"],r["rows"]) for r in counts])
    print("UI weekly store totals:",[(r["method"],r["forecast_total"],r["previous_week_units"]) for r in summaries])
    print("Archive:",archive)


if __name__ == "__main__":
    main()
