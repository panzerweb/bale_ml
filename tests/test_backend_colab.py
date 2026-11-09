"""Stdlib verification of file-only backend-ID synthetic inputs and Colab handoff."""
import contextlib
import csv
from datetime import date, datetime, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from prepare_backend_colab import INPUT_LOADER, NOTEBOOK_NAME, ZIP_NAME, generate_inputs, prepare


def read_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


class BackendDatasetTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / "ml_outputs"
        parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent, prefix="backend-input-test-")
        self.directory = Path(self.temp.name)
        self.assertEqual(self.directory.resolve().parent, parent.resolve())
        self.catalog = self.directory / "catalog.json"
        self.document = {"contract": "market-demand-catalog-v1", "source_database": "bale", "variants": [
            {"store_id": 7, "store_name": "Test one", "city": "Panabo City", "barangay": "Gredu",
             "product_id": 80, "product_name": "Water", "category_id": 2, "category_name": "Drinks", "variant_id": 91,
             "sku": "W500", "variant_attributes": {"size": "500 mL"}},
            {"store_id": 7, "store_name": "Test one", "city": "Panabo City", "barangay": "Gredu",
             "product_id": 80, "product_name": "Water", "category_id": 2, "category_name": "Drinks", "variant_id": 92,
             "sku": "W1000", "variant_attributes": {"size": "1 L"}},
            {"store_id": 8, "store_name": "Test two", "city": "Panabo", "barangay": "Santo Ni\u00f1o",
             "product_id": 81, "product_name": "Crackers", "category_id": 3, "category_name": "Snacks", "variant_id": 93,
             "sku": "C30", "variant_attributes": {"pack": "10 pieces"}},
        ]}
        self.catalog.write_text(json.dumps(self.document), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def generate(self, name="inputs", **kwargs):
        path = self.directory / name
        manifest = generate_inputs(self.catalog, path, end_date="2026-11-08", rows=1000, **kwargs)
        return path, manifest

    def test_native_ids_exact_counts_dates_units_and_hashes(self):
        path, manifest = self.generate()
        rows = read_csv(path / "transactions.csv")
        self.assertEqual(len(rows), 1000)
        self.assertEqual({r["store_id"] for r in rows}, {"7", "8"})
        self.assertEqual({r["variant_id"] for r in rows}, {"91", "92", "93"})
        self.assertEqual({r["unit_label"] for r in rows}, {"sellable_unit"})
        lookup = {str(row["variant_id"]): row for row in self.document["variants"]}
        for row in rows:
            variant = lookup[row["variant_id"]]
            self.assertEqual((row["store_id"], row["product_id"], row["category_id"]),
                             tuple(str(variant[key]) for key in ("store_id", "product_id", "category_id")))
            event, known = datetime.fromisoformat(row["transaction_datetime"]), datetime.fromisoformat(row["known_at"])
            self.assertTrue(date(2026, 5, 13) <= event.date() <= date(2026, 11, 8))
            self.assertEqual(known.date(), event.date() + timedelta(days=1))
            self.assertEqual((known.hour, known.minute), (0, 5))
            self.assertGreater(int(row["quantity"]), 0)
        self.assertEqual(len({r["transaction_item_id"] for r in rows}), len(rows))
        self.assertEqual(manifest["recorded_units"], sum(int(row["quantity"]) for row in rows))
        for name, checksum in manifest["files"].items():
            self.assertEqual(hashlib.sha256((path / name).read_bytes()).hexdigest(), checksum)
        mappings = json.loads((path / "backend_mappings.json").read_text())
        self.assertEqual({r["store_id"] for r in mappings["stores"]}, {7, 8})
        self.assertEqual({r["variant_id"] for r in mappings["units"]}, {91, 92, 93})

    def test_coverage_and_activity_at_every_weekly_evaluation_cutoff(self):
        path, _ = self.generate()
        coverage = read_csv(path / "coverage.csv")
        daily = read_csv(path / "store_daily_observations.csv")
        self.assertEqual(len(coverage), 2 * 180)
        self.assertEqual({r["reporting_status"] for r in coverage}, {"complete"})
        self.assertEqual({r["availability_status"] for r in coverage}, {"unknown"})
        for offset in [0, 84, 77, 70, 63, 56, 49, 42, 35, 28, 21, 14, 7]:
            cutoff = date(2026, 11, 8) - timedelta(days=offset)
            for store in ("7", "8"):
                history = [r for r in daily if r["store_id"] == store and date.fromisoformat(r["date"]) <= cutoff]
                self.assertGreaterEqual(len(history), 56)
                recent = history[-28:]
                self.assertEqual(len(recent), 28)
                self.assertGreaterEqual(sum(int(r["units_sold"]) > 0 for r in recent), 7)
        self.assertEqual(sum(int(r["units_sold"]) for r in daily), sum(int(r["units_sold"]) for r in read_csv(path / "area_daily_observations.csv")))

    def test_reproducible_generation_and_refusal_to_overwrite(self):
        first, a = self.generate("first")
        second, b = self.generate("second")
        self.assertEqual(a, b)
        for name in a["files"]:
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
        with self.assertRaises(FileExistsError):
            generate_inputs(self.catalog, first, rows=1000, end_date="2026-11-08")

    def test_unknown_locations_fail_before_writing(self):
        self.document["variants"][0]["barangay"] = "Unreviewed area"
        self.catalog.write_text(json.dumps(self.document), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unreviewed location"):
            self.generate()
        self.assertFalse((self.directory / "inputs").exists())

    def test_duplicate_variant_identity_fails_before_writing(self):
        self.document["variants"].append(dict(self.document["variants"][0]))
        self.catalog.write_text(json.dumps(self.document), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate variant"):
            self.generate()
        self.assertFalse((self.directory / "inputs").exists())

    def test_notebook_preserves_all_training_function_cells_and_loads_input_zip(self):
        path = self.directory / "handoff"
        prepare(self.catalog, path, rows=1000, end_date="2026-11-08")
        canonical = json.loads((ROOT / "Panabo_Area_Demand_Forecastingg.ipynb").read_text(encoding="utf-8"))
        notebook = json.loads((path / NOTEBOOK_NAME).read_text(encoding="utf-8"))
        by_id = {cell["id"]: cell for cell in notebook["cells"]}
        for cell in canonical["cells"]:
            if cell["cell_type"] == "code" and "config" not in cell.get("metadata", {}).get("tags", []):
                self.assertEqual(cell["source"], by_id[cell["id"]]["source"])
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                compile("".join(cell["source"]), cell["id"], "exec")
                self.assertEqual(cell["outputs"], [])
        original = Path.cwd()
        try:
            os.chdir(path)
            with contextlib.redirect_stdout(io.StringIO()):
                namespace = {}
                exec(INPUT_LOADER, namespace)
            self.assertEqual(len(read_csv(path / "backend_demo_inputs/transactions.csv")), 1000)
        finally:
            os.chdir(original)
        with zipfile.ZipFile(path / ZIP_NAME) as archive:
            self.assertNotIn("backend_catalog.json", archive.namelist())
            self.assertNotIn("backend_mappings.json", archive.namelist())


if __name__ == "__main__":
    unittest.main(verbosity=2)
