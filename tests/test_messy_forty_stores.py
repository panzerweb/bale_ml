"""Exercise the forty-store ZIP using the unchanged notebook's real cleaning/panel code."""
import contextlib
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from generate_messy_backend import generate_messy
from messy_forty_stores import EXPECTED_AUDIT,ZIP_NAME


class FortyStoreTests(unittest.TestCase):
    profile = "forty_stores"
    zip_name = ZIP_NAME
    @classmethod
    def setUpClass(cls):
        parent = ROOT/"ml_outputs"
        parent.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=parent,prefix="forty-store-test-")
        cls.directory = Path(cls.temp.name)
        labels = ["Rice and Grains","Drinks","Snacks","Health and Beauty","Household","Gadgets","School and Office"]
        cls.catalog = cls.directory/"catalog.json"
        document = {"contract":"market-demand-catalog-v1","variants":[]}
        product,variant = 0,0
        for store,barangay,categories in [(1000000000,"Gredu",range(1,8)),(2,"Santo Ni\u00f1o",range(1,6)),(3,"San Francisco",[2,3,6,7])]:
            for category in categories:
                product += 1
                product_id = 1000000000 if product == 1 else product
                for size in [1,2]:
                    variant += 1
                    variant_id = 1000000000 if variant == 1 else variant
                    document["variants"].append({"store_id":store,"store_name":f"Original {store}",
                        "city":"Panabo","barangay":barangay,"product_id":product_id,"product_name":f"Product {product}",
                        "category_id":category,"category_name":labels[category-1],"variant_id":variant_id,
                        "sku":f"V-{variant_id}","variant_attributes":{"size":str(size)}})
        cls.original_catalog = document
        cls.catalog.write_text(json.dumps(document),encoding="utf-8")
        cls.output = cls.directory/"inputs"
        cls.manifest = generate_messy(cls.catalog,cls.output,profile=cls.profile)
        cls.ns = {}
        cls.notebook_hashes = {}
        for name in ["Bale_Backend_Demo_Colab.ipynb","Panabo_Area_Demand_Forecastingg.ipynb"]:
            cls.notebook_hashes[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        notebook = json.loads((ROOT/"Panabo_Area_Demand_Forecastingg.ipynb").read_text(encoding="utf-8"))
        for cell in notebook["cells"]:
            if set(cell.get("metadata",{}).get("tags",[])) & {"config","functions"}:
                with contextlib.redirect_stdout(io.StringIO()):
                    exec(compile(cell["source"],cell["id"],"exec"),cls.ns)
        cls.pd = cls.ns["pd"]
        cls.ns["AREA_REGISTRY"] = cls.pd.read_csv(cls.output/"areas.csv",dtype="string")[["city","barangay","area_id"]].to_dict("records")
        cls.config = cls.ns["current_config"]()
        cls.raw = cls.pd.read_csv(cls.output/"transactions.csv",dtype="string",keep_default_na=False)
        cls.tx,cls.q,cls.duplicates,cls.blocked,cls.audit = cls.ns["clean_transactions"](cls.raw,cls.config)
        cls.cov = cls.ns["prepare_coverage"](cls.pd.read_csv(cls.output/"coverage.csv",dtype="string",keep_default_na=False),cls.config)
        cls.cutoff = cls.pd.Timestamp(cls.manifest["end"])
        cls.as_of = cls.ns["parse_timestamp"](cls.manifest["as_of"])
        cls.panels = {}
        for scope in ["GROUP","STORE_GROUP"]:
            cls.panels[scope] = cls.ns["daily_panel"](cls.tx,cls.cov,cls.cutoff,cls.as_of,cls.blocked,cls.ns[scope])

    @classmethod
    def tearDownClass(cls):
        try:
            for name,checksum in cls.notebook_hashes.items():
                if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != checksum:
                    raise AssertionError("Notebook changed: "+name)
        finally:
            if cls.directory.resolve().parent != (ROOT/"ml_outputs").resolve():
                raise RuntimeError("Refusing cleanup outside the test workspace")
            cls.temp.cleanup()

    def test_store_distribution_and_collision_free_identity_expansion(self):
        pd = self.pd
        stores = pd.read_csv(self.output/"stores.csv",dtype="string")
        products = pd.read_csv(self.output/"products.csv",dtype="string")
        self.assertEqual(len(stores),40)
        self.assertEqual(set(stores.groupby("area_id").size()),{4})
        self.assertEqual(stores.area_id.nunique(),10)
        self.assertEqual(self.manifest["store_category_groups"],275)
        self.assertEqual(self.manifest["area_category_groups"],70)
        originals = {str(r["store_id"]) for r in self.original_catalog["variants"]}
        fictional = set(self.manifest["fictional_store_ids"])
        self.assertEqual(len(fictional),37)
        self.assertFalse(originals & fictional)
        self.assertNotIn("1000000000",fictional)
        self.assertTrue(all(int(value)>=1000000000 for value in fictional))
        original_product_ids = {str(r["product_id"]) for r in self.original_catalog["variants"]}
        original_variant_ids = {str(r["variant_id"]) for r in self.original_catalog["variants"]}
        added = products.loc[products.store_id.isin(fictional)]
        self.assertFalse(original_product_ids & set(added.product_id))
        self.assertFalse(original_variant_ids & set(added.variant_id))
        self.assertTrue(added.groupby("store_id").category_id.nunique().eq(7).all())
        self.assertTrue(added.groupby(["store_id","category_id"]).size().eq(2).all())
        self.assertFalse(products.variant_id.duplicated().any())
        lookup = products.set_index("variant_id")
        for source in self.original_catalog["variants"]:
            row = lookup.loc[str(source["variant_id"])]
            self.assertEqual((row.store_id,row.product_id,row.category_id),tuple(str(source[k]) for k in ["store_id","product_id","category_id"]))
        self.assertEqual(set(self.tx.store_id),set(stores.store_id))
        matched = self.tx.merge(products[["variant_id","store_id","product_id","category_id"]],on="variant_id",suffixes=("","_catalog"),validate="many_to_one")
        for column in ["store_id","product_id","category_id"]:
            self.assertTrue(matched[column].eq(matched[column+"_catalog"]).all())

    def test_cleaning_counts_and_accepted_units(self):
        for key,value in EXPECTED_AUDIT.items():
            self.assertEqual(self.audit[key],value,key)
        self.assertEqual(self.q.reason.value_counts().to_dict(),{
            "conflicting_duplicate;":80,"invalid_quantity;":48,"invalid_product_id;":24,"unsupported_status;":24})
        self.assertEqual(len(self.blocked[self.ns["GROUP"]].drop_duplicates()),4)
        self.assertEqual(float(self.tx.quantity.sum()),self.manifest["recorded_units"])
        self.assertGreaterEqual(int(self.raw.city.str.contains("Panabo City").sum()),1600)
        self.assertTrue(self.tx.city.eq("panabo").all())

    def test_affected_area_totals_withheld_while_other_stores_remain_eligible(self):
        scenarios = self.manifest["intentional_scenarios"]
        targets = scenarios["corrupt_store_categories"]+scenarios["partial_store_categories"]
        area_expected = {(r["area_id"],r["category_id"]) for r in targets}
        store_expected = {(r["store_id"],r["area_id"],r["category_id"]) for r in targets}
        for scope,expected in [("GROUP",area_expected),("STORE_GROUP",store_expected)]:
            statuses = self.ns["eligibility"](self.panels[scope],self.cutoff,self.ns[scope])
            missing = set(statuses.loc[statuses.status.ne("eligible"),self.ns[scope]].itertuples(index=False,name=None))
            self.assertTrue(expected <= missing)
        statuses = self.ns["eligibility"](self.panels["STORE_GROUP"],self.cutoff,self.ns["STORE_GROUP"])
        for row in scenarios["corrupt_store_categories"]:
            others = statuses.loc[statuses.area_id.eq(row["area_id"]) & statuses.category_id.eq(row["category_id"]) & statuses.store_id.ne(row["store_id"])]
            self.assertGreater(len(others),0)
            self.assertTrue(others.status.eq("eligible").all())

    def test_current_daily_sidecars_match_real_notebook_panels(self):
        for scope,filename in [("GROUP","area_daily_observations.csv"),("STORE_GROUP","store_daily_observations.csv")]:
            keys = self.ns[scope]+["date"]
            fields = keys+["units_sold","observation_status"]
            sidecar = self.pd.read_csv(self.output/filename,dtype={k:str for k in self.ns[scope]},parse_dates=["date"])
            actual = self.panels[scope][fields].sort_values(keys).reset_index(drop=True)
            expected = sidecar[fields].sort_values(keys).reset_index(drop=True)
            self.pd.testing.assert_frame_equal(actual,expected,check_dtype=False)
        self.assertTrue(self.panels["STORE_GROUP"].units_sold.eq(0).any())

    def test_late_reports_are_unavailable_until_known(self):
        scenarios = self.manifest["intentional_scenarios"]
        for value in scenarios["late_reporting_dates"]:
            end = self.pd.Timestamp(value)
            report_time = self.cov.loc[self.cov.date.eq(end) & self.cov.store_id.eq(scenarios["late_store_categories"][0]["store_id"]) &
                                      self.cov.category_id.eq(scenarios["late_store_categories"][0]["category_id"]),"known_at"].iloc[0]
            before = self.ns["daily_panel"](self.tx,self.cov,end,self.ns["issuance_time"](end),self.blocked,self.ns["STORE_GROUP"])
            after = self.ns["daily_panel"](self.tx,self.cov,end,report_time+self.pd.Timedelta(minutes=1),self.blocked,self.ns["STORE_GROUP"])
            for row in scenarios["late_store_categories"]:
                def selected(frame):
                    return frame.loc[frame.store_id.eq(row["store_id"]) & frame.category_id.eq(row["category_id"]) & frame.date.eq(end),"units_sold"]
                self.assertTrue(selected(before).isna().all())
                self.assertTrue(selected(after).notna().all())

    def test_zip_checksums_size_and_reproducibility(self):
        expected = {"transactions.csv","coverage.csv","areas.csv","stores.csv","categories.csv","products.csv",
                    "store_daily_observations.csv","area_daily_observations.csv","dataset_manifest.json"}
        with zipfile.ZipFile(self.output/self.zip_name) as archive:
            self.assertEqual(len(archive.infolist()),9)
            self.assertEqual(set(archive.namelist()),expected)
            self.assertLessEqual(sum(i.file_size for i in archive.infolist()),100*1024*1024)
            for name,checksum in self.manifest["files"].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(),checksum)
        second = self.directory/"repeat"
        repeated = generate_messy(self.catalog,second,profile=self.profile)
        self.assertEqual(self.manifest,repeated)
        self.assertEqual((self.output/self.zip_name).read_bytes(),(second/self.zip_name).read_bytes())
        self.assertFalse(list(self.output.glob("*.ipynb")))
        with self.assertRaises(FileExistsError):
            generate_messy(self.catalog,self.output,profile=self.profile)


if __name__ == "__main__":
    unittest.main(verbosity=2)
