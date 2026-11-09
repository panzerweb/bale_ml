"""Verify intentional dirty rows against the actual, unchanged notebook pipeline."""
import contextlib
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
sys.path.insert(0,str(ROOT/"scripts"))
from generate_messy_backend import EXPECTED_AUDIT, ZIP_NAME, generate_messy
from prepare_backend_colab import INPUT_LOADER


class MessyInputsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = ROOT/"ml_outputs"
        parent.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=parent,prefix="messy-test-")
        cls.directory = Path(cls.temp.name)
        cls.notebook_hashes = {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
                               ["Bale_Backend_Demo_Colab.ipynb","Panabo_Area_Demand_Forecastingg.ipynb"]}
        catalog = {"contract":"market-demand-catalog-v1", "variants":[]}
        for i,(store,barangay,category,label) in enumerate([
            (1,"Gredu",1,"Rice and Grains"),(1,"Gredu",2,"Drinks"),
            (2,"San Francisco",3,"Snacks"),(3,"Santo Ni\u00f1o",4,"Household")],1):
            catalog["variants"].append({"store_id":store,"store_name":f"Store {store}",
                "city":"Panabo","barangay":barangay,"product_id":i,"product_name":f"Product {i}",
                "category_id":category,"category_name":label,"variant_id":i,"sku":f"S{i}","variant_attributes":{}})
        cls.catalog = cls.directory/"catalog.json"
        cls.catalog.write_text(json.dumps(catalog),encoding="utf-8")
        cls.output = cls.directory/"inputs"
        cls.manifest = generate_messy(cls.catalog,cls.output)
        cls.ns = {}
        notebook = json.loads((ROOT/"Panabo_Area_Demand_Forecastingg.ipynb").read_text(encoding="utf-8"))
        for cell in notebook["cells"]:
            if set(cell.get("metadata",{}).get("tags",[])) & {"config","functions"}:
                with contextlib.redirect_stdout(io.StringIO()):
                    exec(compile(cell["source"],cell["id"],"exec"),cls.ns)
        cls.pd = cls.ns["pd"]
        cls.ns["AREA_REGISTRY"] = cls.pd.read_csv(cls.output/"areas.csv",dtype="string")[["area_id","city","barangay"]].to_dict("records")
        cls.config = cls.ns["current_config"]()
        cls.raw = cls.pd.read_csv(cls.output/"transactions.csv",dtype="string",keep_default_na=False)
        cls.tx,cls.quarantine,cls.duplicates,cls.blocked,cls.audit = cls.ns["clean_transactions"](cls.raw,cls.config)
        cls.coverage = cls.ns["prepare_coverage"](cls.pd.read_csv(cls.output/"coverage.csv",dtype="string",keep_default_na=False),cls.config)
        cls.cutoff = cls.pd.Timestamp(cls.manifest["end"])
        cls.as_of = cls.ns["parse_timestamp"](cls.manifest["as_of"])

    @classmethod
    def tearDownClass(cls):
        try:
            for p,expected in cls.notebook_hashes.items():
                if hashlib.sha256((ROOT/p).read_bytes()).hexdigest() != expected:
                    raise AssertionError("Notebook changed: "+p)
        finally:
            if cls.directory.resolve().parent != (ROOT/"ml_outputs").resolve():
                raise RuntimeError("Refusing cleanup outside test workspace")
            cls.temp.cleanup()

    def test_exact_audit_and_scoped_quarantine(self):
        for key,value in EXPECTED_AUDIT.items():
            self.assertEqual(self.audit[key],value,key)
        self.assertEqual(self.quarantine.reason.value_counts().to_dict(),{
            "conflicting_duplicate;":20,"invalid_quantity;":12,"invalid_product_id;":6,"unsupported_status;":6})
        self.assertEqual(len(self.blocked[self.ns["GROUP"]].drop_duplicates()),1)
        self.assertEqual(float(self.tx.quantity.sum()),self.manifest["recorded_units"])
        self.assertTrue(self.tx.quantity.gt(0).all())

    def test_reproducible_zip_and_no_notebook_output(self):
        second = self.directory/"repeat"
        other = generate_messy(self.catalog,second)
        self.assertEqual(self.manifest,other)
        self.assertEqual((self.output/ZIP_NAME).read_bytes(),(second/ZIP_NAME).read_bytes())
        self.assertFalse(list(self.output.glob("*.ipynb")))
        with self.assertRaises(FileExistsError):
            generate_messy(self.catalog,self.output)

    def test_zip_contract_and_unchanged_loader(self):
        expected = {"transactions.csv","coverage.csv","areas.csv","stores.csv","categories.csv","products.csv",
                    "store_daily_observations.csv","area_daily_observations.csv","dataset_manifest.json"}
        with zipfile.ZipFile(self.output/ZIP_NAME) as archive:
            self.assertEqual(set(archive.namelist()),expected)
            self.assertEqual(len(archive.infolist()),len(expected))
            for name,checksum in self.manifest["files"].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(),checksum)
        loader = self.directory/"loader"
        loader.mkdir()
        (loader/"Bale_Backend_Demo_Inputs.zip").write_bytes((self.output/ZIP_NAME).read_bytes())
        original = Path.cwd()
        try:
            os.chdir(loader)
            with contextlib.redirect_stdout(io.StringIO()):
                scope = {}
                exec(INPUT_LOADER,scope)
            self.assertEqual(scope["_bale_manifest"]["rows"],50000)
        finally:
            os.chdir(original)

    def test_normalization_and_input_order(self):
        self.assertGreaterEqual(int(self.raw.city.str.contains("Panabo City").sum()),400)
        self.assertTrue(self.tx.city.eq("panabo").all())
        self.assertFalse(self.tx.barangay.str.contains("brgy",case=False).any())
        self.assertTrue(self.tx.unit_label.eq("sellable_unit").all())
        changed,_,_,_,audit = self.ns["clean_transactions"](self.raw.sample(frac=1,random_state=1),self.config)
        self.assertEqual(audit,self.audit)
        keys = ["store_id","category_id","date"]
        self.pd.testing.assert_series_equal(self.tx.groupby(keys).quantity.sum(),changed.groupby(keys).quantity.sum())

    def test_current_withholding_and_observation_sidecars(self):
        for columns,filename in [(self.ns["GROUP"],"area_daily_observations.csv"),
                                 (self.ns["STORE_GROUP"],"store_daily_observations.csv")]:
            panel = self.ns["daily_panel"](self.tx,self.coverage,self.cutoff,self.as_of,self.blocked,columns)
            statuses = self.ns["eligibility"](panel,self.cutoff,columns)
            self.assertEqual(int(statuses.status.eq("eligible").sum()),2)
            self.assertEqual(set(statuses.status),{"eligible","insufficient_history","incomplete_reporting"})
            sidecar = self.pd.read_csv(self.output/filename,dtype={k:str for k in columns},parse_dates=["date"])
            fields = [*columns,"date","units_sold","observation_status"]
            keys = [*columns,"date"]
            actual = panel[fields].sort_values(keys).reset_index(drop=True)
            expected = sidecar[fields].sort_values(keys).reset_index(drop=True)
            self.pd.testing.assert_frame_equal(actual,expected,check_dtype=False)
            healthy = panel.loc[panel.observation_status.eq("complete")]
            self.assertTrue(healthy.units_sold.eq(0).any())

    def test_late_reports_cannot_leak_into_earlier_forecasts(self):
        scenarios = self.manifest["intentional_scenarios"]
        store,category = scenarios["late_store_category"]
        for value in scenarios["late_reporting_dates"]:
            end = self.pd.Timestamp(value)
            before = self.ns["daily_panel"](self.tx,self.coverage,end,self.ns["issuance_time"](end),self.blocked,self.ns["STORE_GROUP"])
            mask = before.store_id.eq(store) & before.category_id.eq(category) & before.date.eq(end)
            self.assertTrue(before.loc[mask,"units_sold"].isna().all())
            report = self.coverage.loc[self.coverage.store_id.eq(store) & self.coverage.category_id.eq(category) & self.coverage.date.eq(end)].iloc[0]
            after = self.ns["daily_panel"](self.tx,self.coverage,end,report.known_at+self.pd.Timedelta(minutes=1),self.blocked,self.ns["STORE_GROUP"])
            mask = after.store_id.eq(store) & after.category_id.eq(category) & after.date.eq(end)
            self.assertTrue(after.loc[mask,"units_sold"].notna().all())
            expected = self.tx.loc[self.tx.store_id.eq(store) & self.tx.category_id.eq(category) & self.tx.date.eq(end),"quantity"].sum()
            self.assertEqual(after.loc[mask,"units_sold"].iloc[0],expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
