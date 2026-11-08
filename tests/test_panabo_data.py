"""Validate the delivered city dataset and its actual notebook integration.

Run: python tests/test_panabo_data.py
The generator/file tests need only the standard library; notebook checks need pandas/numpy.
"""
import contextlib
import csv
from datetime import date, datetime, timedelta
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"scripts"))
from generate_panabo import generate_panabo, panabo_preset, panabo_sha256, PANABO_COLUMNS
from sync_panabo_notebook import embedded_source

DATA = ROOT/"demo_data/panabo_50k"
REFERENCE = json.loads((ROOT/"data/panabo_reference.json").read_text(encoding="utf-8"))
NB = json.loads((ROOT/"Panabo_Area_Demand_Forecastingg.ipynb").read_text(encoding="utf-8"))


def read_csv(name):
    with (DATA/name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


@contextlib.contextmanager
def dataset_workspace():
    # tempfile.mkdtemp creates inaccessible directories in this Windows sandbox.
    parent = (ROOT/"ml_outputs").resolve()
    parent.mkdir(exist_ok=True)
    directory = parent/("panabo-verification-"+uuid.uuid4().hex)
    directory.mkdir()
    try:
        yield directory
    finally:
        if directory.resolve().parent != parent:
            raise RuntimeError("Refusing cleanup outside the verification workspace")
        shutil.rmtree(directory)


class DatasetTests(unittest.TestCase):
    def test_delivered_counts_checksums_and_determinism(self):
        manifest = json.loads((DATA/"dataset_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["start"], "2026-05-13")
        self.assertEqual(manifest["end"], "2026-11-08")
        self.assertEqual(manifest["row_counts"]["transactions.csv"], 50000)
        self.assertEqual(manifest["row_counts"]["coverage.csv"], 57600)
        self.assertEqual(manifest["row_counts"]["area_daily_observations.csv"], 28800)
        self.assertEqual(manifest["row_counts"]["store_daily_observations.csv"], 57600)
        with dataset_workspace() as temp:
            generate_panabo(temp)
            for filename, checksum in manifest["files"].items():
                self.assertEqual(panabo_sha256(DATA/filename), checksum)
                self.assertEqual((Path(temp)/filename).read_bytes(), (DATA/filename).read_bytes())
            self.assertEqual((Path(temp)/"dataset_manifest.json").read_bytes(), (DATA/"dataset_manifest.json").read_bytes())
            broken = Path(temp)/"transactions.csv"
            broken.write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                panabo_preset(temp, REFERENCE)

    def test_line_identity_dates_and_catalog_references(self):
        sales = read_csv("transactions.csv")
        stores = {r["store_id"]:r for r in read_csv("stores.csv")}
        products = {r["product_id"]:r for r in read_csv("products.csv")}
        self.assertEqual(list(sales[0]), PANABO_COLUMNS)
        self.assertEqual(len(sales), 50000)
        self.assertEqual(len({r["transaction_item_id"] for r in sales}), len(sales))
        self.assertEqual(len(stores), 80)
        self.assertEqual(len({r["barangay"] for r in sales}), 40)
        self.assertEqual(len({r["category_id"] for r in sales}), 4)
        for r in sales:
            self.assertEqual(r["barangay"], stores[r["store_id"]]["barangay"])
            product = products[r["product_id"]]
            self.assertEqual((r["category_id"],r["unit_label"],r["variant_id"]),
                             (product["category_id"],product["unit_label"],product["variant_id"]))
            event, known = map(datetime.fromisoformat, [r["transaction_datetime"], r["known_at"]])
            self.assertEqual(event.utcoffset(), timedelta(hours=8))
            self.assertTrue(date(2026,5,13) <= event.date() <= date(2026,11,8))
            self.assertEqual(known.date(), event.date()+timedelta(days=1))
            self.assertEqual((known.hour,known.minute), (0,5))
            self.assertGreater(int(r["quantity"]), 0)

    def test_geography_and_custom_generation(self):
        areas = read_csv("areas.csv")
        self.assertEqual(len(areas), 40)
        self.assertEqual(len({r["area_id"] for r in areas}), 40)
        for r in areas:
            self.assertTrue(r["area_id"].isdigit() and len(r["area_id"]) == 10)
            self.assertEqual(bool(r["latitude"]), bool(r["longitude"]))
            if r["latitude"]:
                self.assertTrue(-90 <= float(r["latitude"]) <= 90)
                self.assertTrue(-180 <= float(r["longitude"]) <= 180)
            self.assertIn("not a store location", r["coordinate_source"])
            self.assertTrue(r["coordinate_source_url"].startswith("https://www.philatlas.com/"))
        with dataset_workspace() as temp:
            with self.assertRaisesRegex(ValueError, "at least"):
                generate_panabo(temp, days=30)
            with self.assertRaisesRegex(ValueError, "at least"):
                generate_panabo(temp, rows=10000)
            generate_panabo(temp, end_date="2026-10-31", days=90, rows=12000, seed=17)
            preset = panabo_preset(temp, REFERENCE)
            self.assertEqual(preset["cutoff"], "2026-10-31")
            self.assertEqual(preset["manifest"]["rows"], 12000)

    def test_embedded_generator_matches_sources(self):
        cell = next(c for c in NB["cells"] if c["id"] == "panabo-city-generator")
        self.assertEqual(cell["source"], embedded_source())


@unittest.skipUnless(importlib.util.find_spec("pandas") and importlib.util.find_spec("numpy"), "Notebook checks require pandas and numpy")
class NotebookIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = {}
        for c in NB["cells"]:
            if set(c["metadata"].get("tags", [])) & {"config", "functions"}:
                with contextlib.redirect_stdout(io.StringIO()):
                    exec(compile(c["source"], c["id"], "exec"), cls.ns)
        cls.ns["DEMO_DIRECTORY"] = DATA
        load = next(c for c in NB["cells"] if "load" in c["metadata"].get("tags", []))
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(load["source"].split("\nimport joblib")[0], load["id"], "exec"), cls.ns)
        ns = cls.ns
        cls.pd = ns["pd"]
        config = ns["current_config"]()
        cls.tx, cls.quarantine, cls.duplicates, cls.blocked, cls.audit = ns["clean_transactions"](
            cls.pd.read_csv(DATA/"transactions.csv", dtype="string", keep_default_na=False), config)
        cls.cov = ns["prepare_coverage"](cls.pd.read_csv(DATA/"coverage.csv", dtype="string"), config)
        cls.panel = ns["daily_panel"](cls.tx, cls.cov, ns["cutoff"], ns["as_of"], cls.blocked)
        cls.store_panel = ns["daily_panel"](cls.tx, cls.cov, ns["cutoff"], ns["as_of"], cls.blocked, ns["STORE_GROUP"])

    def test_preset_cutoff_and_cleaning(self):
        self.assertEqual(str(self.ns["cutoff"].date()), "2026-11-08")
        self.assertEqual(self.ns["as_of"].tz_convert("Asia/Manila").isoformat(), "2026-11-09T00:15:00+08:00")
        self.assertEqual(self.ns["DATA_KIND"], "synthetic")
        self.assertEqual(len(self.quarantine), 0)
        self.assertEqual(len(self.duplicates), 0)
        self.assertFalse(self.audit["global_block"])
        self.assertEqual(set(self.panel.area_id), {a["area_id"] for a in REFERENCE["areas"]})

    def test_full_coverage_reconciliation_and_zero_days(self):
        self.assertEqual(len(self.panel), 28800)
        self.assertEqual(len(self.store_panel), 57600)
        self.assertFalse(self.panel.units_sold.isna().any())
        self.assertFalse(self.store_panel.units_sold.isna().any())
        self.assertGreater(int(self.store_panel.units_sold.eq(0).sum()), 0)
        for actual, filename, keys in [
            (self.panel,"area_daily_observations.csv",self.ns["GROUP"]+["date"]),
            (self.store_panel,"store_daily_observations.csv",self.ns["STORE_GROUP"]+["date"])]:
            delivered = self.pd.read_csv(DATA/filename, dtype={"area_id":"string"})
            delivered["date"] = self.pd.to_datetime(delivered.date)
            a = actual.sort_values(keys).units_sold.to_numpy()
            b = delivered.sort_values(keys).units_sold.to_numpy()
            self.ns["np"].testing.assert_array_equal(a, b)
            self.assertEqual(int(actual.units_sold.sum()), int(self.tx.quantity.sum()))

    def test_eligibility_at_all_issuance_cutoffs(self):
        ns = self.ns
        windows = ns["evaluation_windows"](self.panel.date.min(), ns["cutoff"])
        cutoffs = [ns["cutoff"], *windows["validation"], *windows["reserved_calibration"], *windows["final"]]
        for panel, keys in [(self.panel,ns["GROUP"]), (self.store_panel,ns["STORE_GROUP"])]:
            for cutoff in cutoffs:
                statuses = ns["eligibility"](panel.loc[panel.date <= cutoff], cutoff, keys)
                self.assertTrue(statuses.status.eq("eligible").all(), (keys, cutoff, statuses.status.value_counts()))

    def test_baseline_forecast_map_windows_and_missing_location(self):
        ns = self.ns
        future = ns["predict_seven"]("last_week", None, self.panel, ns["cutoff"])
        self.assertEqual(len(future), 1120)
        self.assertEqual(str(future.forecast_date.min().date()), "2026-11-09")
        self.assertEqual(str(future.forecast_date.max().date()), "2026-11-15")
        summaries = ns["map_summaries"](self.panel, future, ns["cutoff"])
        self.assertEqual(len(summaries), 40*5*3)
        self.assertTrue(summaries.coverage_status.eq("complete").all())
        coordinates = ns["prepare_coordinates"](self.pd.read_csv(DATA/"areas.csv", dtype="string"))
        self.assertEqual(set(coordinates.area_id), set(self.panel.area_id))
        missing = coordinates.copy()
        missing.loc[0,["latitude","longitude"]] = float("nan")
        self.assertTrue(ns["prepare_coordinates"](missing).iloc[0][["latitude","longitude"]].isna().all())


if __name__ == "__main__":
    (ROOT/"ml_outputs").mkdir(exist_ok=True)
    unittest.main(verbosity=2)
