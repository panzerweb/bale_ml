"""Exercise functions directly from the standalone notebook; no copied pipeline.

Run: python tests/test_notebook.py
Optional: python tests/test_notebook.py --execute (requires all notebook dependencies).
"""
import ast
import contextlib
import io
import json
from pathlib import Path
import sys
import uuid
import shutil
import unittest
import warnings

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "Panabo_Area_Demand_Forecastingg.ipynb"
nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
ns = {}
for cell in nb["cells"]:
    if set(cell["metadata"].get("tags", [])) & {"config", "functions"}:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(cell["source"], str(NOTEBOOK), "exec"), ns)
pd, np = ns["pd"], ns["np"]


@contextlib.contextmanager
def workspace_temp():
    parent = (ROOT / "ml_outputs").resolve()
    parent.mkdir(exist_ok=True)
    directory = parent / ("verification-" + uuid.uuid4().hex)
    directory.mkdir()
    try:
        yield directory
    finally:
        if directory.resolve().parent != parent:
            raise RuntimeError("Refusing cleanup outside verification directory")
        shutil.rmtree(directory)


class NotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = workspace_temp()
        cls.directory = cls.temp.__enter__()
        cls.paths = ns["generate_demo"](cls.directory, "2026-10-31")
        cls.raw = pd.read_csv(cls.paths[0], dtype="string", keep_default_na=False)
        cls.config = ns["current_config"]()
        cls.tx, _, _, cls.blocked, cls.audit = ns["clean_transactions"](cls.raw, cls.config)
        cls.cov = ns["prepare_coverage"](pd.read_csv(cls.paths[1], dtype="string"), cls.config)
        cls.cutoff = pd.Timestamp("2026-10-31")
        cls.as_of = ns["issuance_time"](cls.cutoff)
        cls.panel = ns["daily_panel"](cls.tx, cls.cov, cls.cutoff, cls.as_of, cls.blocked)
        ns["as_of"] = cls.as_of

    @classmethod
    def tearDownClass(cls):
        cls.temp.__exit__(None, None, None)

    def test_structure_and_syntax(self):
        self.assertEqual(nb["nbformat"], 4)
        self.assertEqual(len({c["id"] for c in nb["cells"]}), len(nb["cells"]))
        for cell in nb["cells"]:
            if cell["cell_type"] == "code":
                ast.parse(cell["source"])
                self.assertIsNone(cell["execution_count"])
                self.assertEqual(cell["outputs"], [])

    def test_demo_deterministic_and_valid(self):
        original = [p.read_bytes() for p in self.paths]
        repeated = ns["generate_demo"](self.directory, "2026-10-31")
        self.assertEqual(original, [p.read_bytes() for p in repeated])
        self.assertEqual(self.audit["quarantined_rows"], 0)
        self.assertEqual(self.tx.area_id.nunique(), 3)
        self.assertEqual(len(self.panel), 180*6)
        self.assertEqual(int(self.panel.units_sold.sum()), int(self.tx.quantity.sum()))
        self.assertTrue(ns["eligibility"](self.panel, self.cutoff).status.eq("eligible").all())

    def test_aliases_and_city_scoping(self):
        canonical = ns["canonical_area"]
        a = canonical(" Panabo City ", "  BRGY.   Salvacion ", self.config)
        b = canonical("Panabo", "Barangay Salvacion", self.config)
        self.assertEqual(a, b)
        self.assertNotEqual(a[2], canonical("Other City", "Salvacion", self.config)[2])
        cfg = dict(self.config, barangay_aliases=[["Panabo", "Salvasion", "Salvacion"]])
        self.assertEqual(a, canonical("Panabo", "Salvasion", cfg))

    def test_identifiers_duplicates_and_conflicts(self):
        raw = self.raw.iloc[:2].copy()
        raw.loc[raw.index[0], "product_id"] = "00001"
        tx, q, duplicate, _, audit = ns["clean_transactions"](pd.concat([raw, raw.iloc[:1]]), self.config)
        self.assertEqual(tx.iloc[0].product_id, "00001")
        self.assertEqual(len(duplicate), 1)
        self.assertEqual(len(q), 0)
        conflict = raw.iloc[:1].copy()
        conflict["quantity"] = "999"
        tx, q, _, _, _ = ns["clean_transactions"](pd.concat([raw, conflict]), self.config)
        self.assertEqual(len(q), 2)
        self.assertTrue(q.reason.str.contains("conflicting_duplicate").all())

    def test_invalid_fields_and_units(self):
        raw = pd.concat([self.raw.iloc[:1]]*6, ignore_index=True)
        raw["transaction_item_id"] = [str(i) for i in range(6)]
        raw.loc[0, "transaction_status"] = ""
        raw.loc[1, "transaction_datetime"] = "2026-08-01 12:00:00"
        raw.loc[2, "quantity"] = "inf"
        raw.loc[3, "quantity"] = "-1"
        raw.loc[4, "unit_label"] = "packs"
        raw.loc[5, "unit_label"] = "BOTTLES"
        tx, q, _, _, _ = ns["clean_transactions"](raw, self.config)
        self.assertEqual(len(q), 4)
        self.assertEqual(set(tx.unit_label), {"pack", "bottle"})
        self.assertTrue(pd.isna(ns["parse_timestamp"]("2026-10-01 12:00")))
        self.assertEqual(ns["parse_timestamp"]("2026-10-01 12:00", "Asia/Manila").hour, 4)

    def test_unknown_mapping_and_missing_schema(self):
        cfg = dict(self.config, area_registry=[{"city":"Other", "barangay":"Other", "area_id":"x"}])
        _, q, _, _, audit = ns["clean_transactions"](self.raw.iloc[:1], cfg)
        self.assertEqual(len(q), 1)
        self.assertTrue(audit["global_block"])
        with self.assertRaises(ValueError):
            ns["clean_transactions"](self.raw.drop(columns="known_at"), self.config)

    def test_gaps_not_zero_and_uncovered_groups_visible(self):
        cov = self.cov.loc[~((self.cov.date == self.cutoff) & (self.cov.store_id == "demo-store-0-0"))]
        panel = ns["daily_panel"](self.tx, cov, self.cutoff, self.as_of, self.blocked)
        affected = ns["canonical_area"]("Panabo", "Salvacion", self.config)[2]
        self.assertTrue(panel.loc[(panel.area_id == affected) & (panel.date == self.cutoff)].units_sold.isna().all())
        absent = ns["daily_panel"](self.tx, self.cov.iloc[:0], self.cutoff, self.as_of, self.blocked)
        self.assertEqual(absent.area_id.nunique(), 3)
        self.assertTrue(absent.units_sold.isna().all())

    def test_eligibility_zero_sparse_short(self):
        self.assertTrue(ns["eligibility"](self.panel.loc[self.panel.date > self.cutoff-pd.Timedelta(days=30)], self.cutoff).status.eq("insufficient_history").all())
        zero = self.panel.copy()
        zero["units_sold"] = 0.
        self.assertTrue(ns["eligibility"](zero, self.cutoff).status.eq("no_sales").all())
        sparse = zero.copy()
        sparse.loc[sparse.date == self.cutoff, "units_sold"] = 1.
        self.assertTrue(ns["eligibility"](sparse, self.cutoff).status.eq("sparse_sales").all())

    def test_features_parity_and_warmup(self):
        examples = ns["training_examples"](self.panel)
        self.assertEqual(len(examples), (180-28)*6)
        key, g = next(iter(self.panel.groupby(ns["GROUP"])))
        g = g.sort_values("date")
        row = ns["feature_row"](key, g.iloc[40].date, g.iloc[:40].units_sold)
        expected = examples.loc[(examples.area_id == key[0]) & (examples.category_id == key[1]) & (examples.date == g.iloc[40].date)].iloc[0]
        for feature in ns["NUMERIC_FEATURES"]:
            self.assertAlmostEqual(row[feature], expected[feature])

    def test_future_and_late_known_mutation(self):
        end = self.cutoff-pd.Timedelta(days=40)
        t0 = ns["issuance_time"](end)
        before = ns["daily_panel"](self.tx, self.cov, end, t0, self.blocked)
        altered = self.tx.copy()
        altered.loc[altered.date > end, "quantity"] = 100000.
        late = altered.iloc[:1].copy()
        late["quantity"] = 900000.
        late["known_at"] = self.as_of
        altered = pd.concat([altered, late])
        after = ns["daily_panel"](altered, self.cov, end, t0, self.blocked)
        pd.testing.assert_frame_equal(before, after)
        forecast_a = ns["predict_seven"]("weekday_average", None, before, end)
        forecast_b = ns["predict_seven"]("weekday_average", None, after, end)
        pd.testing.assert_frame_equal(forecast_a, forecast_b)

    def test_protocols_and_metrics(self):
        long = ns["evaluation_windows"](self.cutoff-pd.Timedelta(days=179), self.cutoff)
        short = ns["evaluation_windows"](self.cutoff-pd.Timedelta(days=89), self.cutoff)
        self.assertEqual([len(long[k]) for k in ["validation", "reserved_calibration", "final"]], [4,4,4])
        self.assertEqual([len(short[k]) for k in ["validation", "final"]], [2,2])
        self.assertLess(max(long["validation"])+pd.Timedelta(days=7), min(long["final"]))
        with self.assertRaises(ValueError):
            ns["evaluation_windows"](self.cutoff-pd.Timedelta(days=60), self.cutoff)
        self.assertIsNone(ns["metrics"](pd.DataFrame({"actual_units":[0.], "predicted_units":[1.]}))["WAPE_pct"])

    def test_guidance_explains_metric_disagreement_and_release(self):
        records = [
            {"method":"lightgbm", "MAE":6.5, "RMSE":8.6},
            {"method":"random_forest", "MAE":6.6, "RMSE":8.5},
            {"method":"weekday_average", "MAE":7.0, "RMSE":9.0}]
        text = ns["validation_explanation"](pd.DataFrame(records))
        self.assertIn("Validation choice: LightGBM", text)
        self.assertIn("Lowest RMSE: Random Forest", text)
        self.assertIn("you do not need to choose", text)
        evaluation = {"mode":"train", "validation":records, "validation_selected_method":"lightgbm",
                      "strongest_validation_baseline":"weekday_average",
                      "final":[{"method":"lightgbm", "MAE":6.8}, {"method":"weekday_average", "MAE":7.0}]}
        text = ns["evaluation_explanation"](evaluation, "lightgbm")
        self.assertIn("reduced average error by 0.20 units (2.9%)", text)
        evaluation["final"][0]["MAE"] = 7.0
        self.assertIn("simple method instead", ns["evaluation_explanation"](evaluation, "weekday_average"))
        evaluation["final"][1]["MAE"] = 0.
        evaluation["final"][0]["MAE"] = 1.
        self.assertNotIn("inf", ns["evaluation_explanation"](evaluation, "weekday_average"))
        evaluation.update(validation_selected_method="weekday_average", final=[{"method":"weekday_average", "MAE":0.}])
        self.assertIn("only that method", ns["evaluation_explanation"](evaluation, "weekday_average"))
        tied = pd.DataFrame([{"method":"lightgbm", "MAE":1., "RMSE":2., "tie_priority":4},
                             {"method":"last_week", "MAE":1., "RMSE":2., "tie_priority":0}])
        self.assertIn("Validation choice: Repeat last week's sales", ns["validation_explanation"](tied))
        self.assertIn("exact MAE tie", ns["validation_explanation"](tied))

    def test_readable_forecasts_do_not_mutate_exports(self):
        before = ns["CATEGORY_LABELS"]
        try:
            ns["CATEGORY_LABELS"] = {1:"Rice and Grains"}
            forecast = ns["predict_seven"]("last_week", None, self.panel, self.cutoff)
            forecast["category_id"] = "1"
            forecast["lower_bound"] = None
            forecast["upper_bound"] = None
            original = forecast.copy(deep=True)
            readable = ns["readable_table"](forecast)
            self.assertTrue(readable.category_name.eq("Rice and Grains").all())
            self.assertTrue(readable.lower_bound.eq("Unavailable").all())
            pd.testing.assert_frame_equal(forecast, original)
            self.assertIn("name unavailable", ns["category_label"]("999"))
            text = ns["forecast_explanation"](forecast, "last_week")
            self.assertIn("Rice and Grains", text)
            self.assertIn("approximately", text)
            self.assertIn("No forecast", ns["forecast_explanation"](forecast.iloc[:0], None))
            self.assertIn("no tree feature-usage", ns["feature_usage"](None, "last_week")[1])
            saved = {"mode":"forecast_only", "training_evaluation":{"final":[{"method":"last_week", "MAE":2.}]}}
            text = ns["evaluation_explanation"](saved, "last_week")
            self.assertIn("No new model comparison", text)
            self.assertIn("earlier evaluation", text)
        finally:
            ns["CATEGORY_LABELS"] = before

    def test_complete_summary_handles_saved_evidence_and_missing_comparisons(self):
        forecast = ns["predict_seven"]("last_week", None, self.panel, self.cutoff)
        saved = {"mode":"forecast_only", "model_training_end":"2026-10-01",
                 "training_evaluation":{"final":[{"method":"last_week", "MAE":2.}]}}
        unknown = {"mode":"train", "message":"Store evaluation unavailable."}
        summary = ns["run_summary"](self.tx, self.panel, ns["eligibility"](self.panel, self.cutoff),
            forecast, self.audit, saved, "last_week", self.cutoff, "synthetic", None, unknown, None)
        self.assertIn("What this run tells you", summary)
        self.assertIn("2026-10-01", summary)
        self.assertIn("No new model comparison", summary)
        self.assertIn("Store evaluation unavailable", summary)
        self.assertIn("generated examples", summary)
        self.assertIn("approximately", summary)
        zero_panel = self.panel.copy()
        zero_panel["units_sold"] = 0.
        text = ns["run_summary"](self.tx, zero_panel, ns["eligibility"](zero_panel, self.cutoff),
            forecast.iloc[:0], self.audit, unknown, "last_week", self.cutoff, "real", None)
        self.assertIn("No forecast was produced", text)
        self.assertIn("No complete positive previous-week comparison", text)
        self.assertNotIn("generated examples", text)

    def test_lightgbm_named_features_warning_and_reload(self):
        import joblib
        estimator = ns["fit_method"]("lightgbm", self.panel)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            forecast = ns["predict_seven"]("lightgbm", estimator, self.panel, self.cutoff)
        self.assertFalse(any("valid feature names" in str(w.message) for w in caught))
        table, explanation = ns["feature_usage"](estimator, "lightgbm")
        self.assertIn("Number of tree splits", table.columns)
        self.assertIn("267 splits", explanation)
        self.assertIn("not why a particular forecast", explanation)
        with workspace_temp() as directory:
            joblib.dump(estimator, directory/"model.joblib")
            loaded = joblib.load(directory/"model.joblib")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                repeated = ns["predict_seven"]("lightgbm", loaded, self.panel, self.cutoff)
            self.assertFalse(any("valid feature names" in str(w.message) for w in caught))
            pd.testing.assert_frame_equal(forecast, repeated)

    def test_guided_charts_keep_selection_and_metric_scope_clear(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        frames = []
        for method in ns["TREE_METHODS"]:
            f = ns["predict_seven"]("last_week", None, self.panel, self.cutoff)
            f["actual_units"] = f.predicted_units + 1
            f["method"] = method
            frames.append(f)
        predictions = pd.concat(frames, ignore_index=True)
        first = predictions.iloc[0]
        comparison = ns["compare_methods"](predictions)
        figures = ns["comparison_figures"](predictions, comparison, predictions, self.panel,
            frames[0], "random_forest", first.area_id, first.category_id, self.cutoff, "synthetic", {})
        self.assertEqual(len(figures), 3)
        self.assertIn("historical checks", figures[0]._bale_guide)
        self.assertIn("all eligible combinations", figures[1]._bale_guide)
        self.assertIn("not proven accuracy", figures[2]._bale_guide)
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            from unittest.mock import patch
            with patch("IPython.display.display", lambda *args:None):
                for fig in figures:
                    ns["show_guided_figure"](fig)
        text = captured.getvalue()
        self.assertEqual(text.count("How to read this chart:"), 3)
        self.assertEqual(text.count("What this shows:"), 3)
        plt.close("all")

    def test_conflict_withholding_respects_availability(self):
        end = self.cutoff-pd.Timedelta(days=40)
        t0 = ns["issuance_time"](end)
        before = ns["daily_panel"](self.tx, self.cov, end, t0, self.blocked)
        future_conflict = pd.DataFrame([{**self.tx.iloc[0][ns["GROUP"]].to_dict(),
            "known_at":self.as_of, "transaction_datetime":self.as_of}])
        after = ns["daily_panel"](self.tx, self.cov, end, t0, future_conflict)
        pd.testing.assert_frame_equal(before, after)
        conflict_now = future_conflict.copy()
        conflict_now["known_at"] = t0
        conflict_now["transaction_datetime"] = t0-pd.Timedelta(hours=12)
        affected = ns["daily_panel"](self.tx, self.cov, end, t0, conflict_now)
        key = tuple(conflict_now.iloc[0][ns["GROUP"]])
        self.assertTrue(affected.loc[affected.area_id.eq(key[0]) & affected.category_id.eq(key[1])].units_sold.isna().all())

    def test_bundle_integrity_and_empty_refusals(self):
        export = next(c for c in nb["cells"] if "export" in c["metadata"].get("tags", []))
        tree = ast.parse(export["source"])
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "verify_bundle")
        exec(compile(ast.Module(body=[function], type_ignores=[]), "verify_bundle", "exec"), ns)
        with workspace_temp() as directory:
            f = ns["predict_seven"]("last_week", None, self.panel, self.cutoff)
            f["run_id"] = "verification"
            f["unit_policy"] = "recorded_sale_units"
            path = directory/"daily_future_forecast.csv"
            f.to_csv(path, index=False)
            status_path = directory/"coverage_summary.csv"
            status_table = ns["eligibility"](self.panel, self.cutoff)
            status_table.to_csv(status_path, index=False)
            metadata = {"run_id":"verification", "forecast_start":"2026-11-01", "forecast_end":"2026-11-07",
                "artifacts":{path.name:ns["sha256_file"](path), status_path.name:ns["sha256_file"](status_path)}}
            ns["json_write"](directory/"run_metadata.json", metadata)
            self.assertTrue(ns["verify_bundle"](directory))
            path.write_text(path.read_text()+"tampered", encoding="utf-8")
            with self.assertRaises(ValueError):
                ns["verify_bundle"](directory)
            f.iloc[:-1].to_csv(path, index=False)
            metadata["artifacts"][path.name] = ns["sha256_file"](path)
            ns["json_write"](directory/"run_metadata.json", metadata)
            with self.assertRaises(ValueError):
                ns["verify_bundle"](directory)
            f.iloc[7:].to_csv(path, index=False)
            # Remove a whole group, even with a recomputed checksum.
            first = f.iloc[0]
            f.loc[~(f.area_id.eq(first.area_id) & f.category_id.eq(first.category_id))].to_csv(path, index=False)
            metadata["artifacts"][path.name] = ns["sha256_file"](path)
            ns["json_write"](directory/"run_metadata.json", metadata)
            with self.assertRaises(ValueError):
                ns["verify_bundle"](directory)
            f.iloc[:0].to_csv(path, index=False)
            status_table["status"] = "no_sales"
            status_table.to_csv(status_path, index=False)
            metadata["artifacts"][status_path.name] = ns["sha256_file"](status_path)
            metadata["artifacts"][path.name] = ns["sha256_file"](path)
            ns["json_write"](directory/"run_metadata.json", metadata)
            self.assertTrue(ns["verify_bundle"](directory))

    def test_baseline_backtests_both_protocols(self):
        for days in [90, 180]:
            start = self.cutoff-pd.Timedelta(days=days-1)
            tx = self.tx.loc[self.tx.date >= start]
            cov = self.cov.loc[self.cov.date >= start]
            windows = ns["evaluation_windows"](start, self.cutoff)
            pred, refusals = ns["backtest"](tx, cov, self.blocked, windows["validation"]+windows["final"] , ns["BASELINES"])
            self.assertEqual(len(pred), len(windows["validation"]+windows["final"])*6*7*2)
            self.assertTrue(np.isfinite(pred.predicted_units).all())
            self.assertTrue(refusals.empty)

    def store_panel(self, tx=None, cov=None, end=None, blocked=None):
        return ns["daily_panel"](self.tx if tx is None else tx, self.cov if cov is None else cov,
            self.cutoff if end is None else end, self.as_of if end is None else ns["issuance_time"](end),
            self.blocked if blocked is None else blocked, ns["STORE_GROUP"])

    def test_store_totals_features_and_independent_gaps(self):
        panel = self.store_panel()
        keys = ns["STORE_GROUP"]
        self.assertEqual(len(panel), 180*18)
        self.assertTrue(ns["eligibility"](panel, self.cutoff, keys).status.eq("eligible").all())
        pd.testing.assert_series_equal(panel.groupby([*ns["GROUP"], "date"]).units_sold.sum(),
                                      self.panel.set_index([*ns["GROUP"], "date"]).units_sold.sort_index())
        examples = ns["training_examples"](panel, keys)
        self.assertEqual(len(examples), 18*(180-28))
        key, g = next(iter(panel.groupby(keys)))
        expected = ns["feature_row"](key, g.iloc[40].date, g.iloc[:40].units_sold, keys)
        row = examples.loc[(examples[keys] == pd.Series(dict(zip(keys, key)))).all(axis=1)
                           & examples.date.eq(g.iloc[40].date)].iloc[0]
        for name in ns["NUMERIC_FEATURES"]:
            self.assertAlmostEqual(row[name], expected[name])
        cov = self.cov.loc[~(self.cov.store_id.eq("demo-store-0-0") & self.cov.date.eq(self.cutoff))]
        with_gap = self.store_panel(cov=cov)
        self.assertTrue(with_gap.loc[with_gap.store_id.eq("demo-store-0-0") & with_gap.date.eq(self.cutoff)].units_sold.isna().all())
        self.assertTrue(with_gap.loc[with_gap.store_id.eq("demo-store-0-1")].units_sold.notna().all())
        statuses = ns["eligibility"](with_gap, self.cutoff, keys)
        usable = ns["eligible_panel"](with_gap, statuses, keys)
        forecast = ns["predict_seven"]("last_week", None, usable, self.cutoff, keys)
        self.assertEqual(len(forecast), 16*7)
        self.assertFalse(forecast.store_id.eq("demo-store-0-0").any())

    def test_store_leakage_and_quarantine_scope(self):
        end = self.cutoff-pd.Timedelta(days=40)
        before = self.store_panel(end=end)
        changed = self.tx.copy()
        changed.loc[changed.date.gt(end), "quantity"] = 900000.
        late = changed.iloc[:1].copy()
        late["known_at"] = self.as_of
        pd.testing.assert_frame_equal(before, self.store_panel(tx=pd.concat([changed, late]), end=end))
        target = self.tx.iloc[0]
        blocked = pd.DataFrame([{**{k:target[k] for k in ns["STORE_GROUP"]},
                                 "known_at":ns["issuance_time"](end),
                                 "transaction_datetime":ns["issuance_time"](end)-pd.Timedelta(hours=12)}])
        affected = self.store_panel(end=end, blocked=blocked)
        mask = affected.store_id.eq(target.store_id) & affected.category_id.eq(target.category_id)
        self.assertTrue(affected.loc[mask].units_sold.isna().all())
        self.assertTrue(affected.loc[~mask].units_sold.notna().all())
        broad = self.store_panel(end=end, blocked=blocked.drop(columns="store_id"))
        self.assertTrue(broad.loc[broad.area_id.eq(target.area_id) & broad.category_id.eq(target.category_id)].units_sold.isna().all())

    def test_store_baseline_evaluation(self):
        panel = self.store_panel()
        original = ns["METHODS"]
        ns["METHODS"] = ns["BASELINES"]
        ns["display"] = lambda *args: None
        try:
            result = ns["evaluate_scope"](panel, self.tx, self.cov, self.blocked, self.cutoff,
                                           ns["STORE_GROUP"], ["synthetic test"])
        finally:
            ns["METHODS"] = original
        self.assertIn(result["published_method"], ns["BASELINES"])
        for stage in ["validation_predictions", "final_predictions"]:
            p = result[stage]
            methods = 2 if stage == "validation_predictions" else len(result["evaluation"]["final"])
            self.assertEqual(len(p), 4*18*7*methods)
            self.assertTrue(p.groupby([*ns["STORE_GROUP"], "cutoff", "forecast_date"]).method.nunique().eq(methods).all())

    def test_map_windows_all_categories_and_missing_forecasts(self):
        forecast = ns["predict_seven"]("last_week", None, self.panel, self.cutoff)
        summary = ns["map_summaries"](self.panel, forecast, self.cutoff)
        self.assertEqual(len(summary), 3*3*3)
        self.assertTrue(summary.coverage_status.eq("complete").all())
        area = self.panel.iloc[0].area_id
        all_id = ns["ALL_CATEGORIES"]
        for days in [90, 180]:
            row = summary.loc[summary.area_id.eq(area) & summary.category_id.eq(all_id)
                              & summary.view.eq("historical") & summary.lookback_days.eq(days)].iloc[0]
            expected = self.panel.loc[self.panel.area_id.eq(area) & self.panel.date.between(
                self.cutoff-pd.Timedelta(days=days-1), self.cutoff)].units_sold.sum()
            self.assertAlmostEqual(row.total_units, expected)
            self.assertEqual(row.start_date, str((self.cutoff-pd.Timedelta(days=days-1)).date()))
        broken = self.panel.copy()
        broken.loc[broken.area_id.eq(area) & broken.date.eq(self.cutoff), "units_sold"] = np.nan
        totals = ns["map_summaries"](broken, forecast, self.cutoff)
        self.assertTrue(totals.loc[totals.area_id.eq(area) & totals.view.eq("historical")].total_units.isna().all())
        missing = forecast.loc[~(forecast.area_id.eq(area) & forecast.category_id.eq("demo-category-0"))]
        totals = ns["map_summaries"](self.panel, missing, self.cutoff)
        self.assertTrue(totals.loc[totals.area_id.eq(area) & totals.category_id.eq(all_id)
                                  & totals.view.eq("forecast")].total_units.isna().all())
        shorter = self.panel.loc[self.panel.date.gt(self.cutoff-pd.Timedelta(days=179))]
        totals = ns["map_summaries"](shorter, forecast, self.cutoff)
        self.assertTrue(totals.loc[totals.lookback_days.eq(180)].total_units.isna().all())
        self.assertTrue(totals.loc[totals.lookback_days.eq(90)].total_units.notna().all())
        zero = self.panel.assign(units_sold=0.)
        zero_future = forecast.assign(predicted_units=0.)
        self.assertTrue(ns["map_summaries"](zero, zero_future, self.cutoff).total_units.eq(0).all())

    def test_coordinates_and_store_saved_identities(self):
        coordinates = ns["demo_coordinates"](self.panel.area_id.unique())
        self.assertEqual(len(coordinates), 3)
        self.assertTrue(coordinates.coordinate_source.str.startswith("synthetic_").all())
        missing = coordinates.copy()
        missing.loc[0, ["latitude", "longitude"]] = np.nan
        self.assertTrue(ns["prepare_coordinates"](missing).iloc[0][["latitude", "longitude"]].isna().all())
        for field, value in [("latitude", 91), ("longitude", "invalid"), ("latitude", float("inf"))]:
            bad = coordinates.astype({field:object}).copy()
            bad.loc[0, field] = value
            with self.assertRaises(ValueError):
                ns["prepare_coordinates"](bad)
        with self.assertRaises(ValueError):
            ns["prepare_coordinates"](pd.concat([coordinates, coordinates.iloc[:1].assign(latitude=0)]))
        panel = self.store_panel()
        keys = ns["STORE_GROUP"]
        statuses = ns["eligibility"](panel, self.cutoff, keys)
        saved = {"supported_groups":statuses[keys].values.tolist(),
                 "cohorts":{json.dumps(tuple(r[k] for k in keys)):r.cohort_id for _, r in statuses.iterrows()}}
        changed = statuses.copy()
        changed.loc[0, "cohort_id"] = "new-cohort"
        changed.loc[1, "store_id"] = "new-store"
        restricted = ns["restrict_saved_groups"](changed, saved, keys)
        self.assertEqual(int(restricted.status.eq("eligible").sum()), 16)

    def test_dashboard_bundle_validation(self):
        export = next(c for c in nb["cells"] if "export" in c["metadata"].get("tags", []))
        function = next(n for n in ast.parse(export["source"]).body if isinstance(n, ast.FunctionDef) and n.name == "verify_bundle")
        exec(compile(ast.Module(body=[function], type_ignores=[]), "verify_bundle", "exec"), ns)
        with workspace_temp() as directory:
            area = ns["predict_seven"]("last_week", None, self.panel, self.cutoff).assign(run_id="test", unit_policy="recorded_sale_units")
            sp = self.store_panel()
            store = ns["predict_seven"]("last_week", None, sp, self.cutoff, ns["STORE_GROUP"]).assign(run_id="test", unit_policy="recorded_sale_units")
            tables = {"daily_future_forecast.csv":area, "coverage_summary.csv":ns["eligibility"](self.panel, self.cutoff),
                "historical_observations.csv":self.panel, "store_daily_future_forecast.csv":store,
                "store_coverage_summary.csv":ns["eligibility"](sp, self.cutoff, ns["STORE_GROUP"]),
                "store_historical_observations.csv":sp, "area_coordinates.csv":ns["demo_coordinates"](self.panel.area_id.unique()),
                "map_summaries.csv":ns["map_summaries"](self.panel, area, self.cutoff).assign(run_id="test")}
            for name, table in tables.items():
                table.to_csv(directory/name, index=False)
            ns["json_write"](directory/"store_evaluation_summary.json", {})
            meta = {"run_id":"test", "forecast_cutoff":str(self.cutoff.date()), "forecast_start":"2026-11-01",
                    "forecast_end":"2026-11-07", "dashboard_version":ns["DASHBOARD_VERSION"], "store_method":"last_week"}
            def refresh_manifest():
                meta["artifacts"] = {p.name:ns["sha256_file"](p) for p in directory.iterdir() if p.name != "run_metadata.json"}
                ns["json_write"](directory/"run_metadata.json", meta)
            refresh_manifest()
            self.assertTrue(ns["verify_bundle"](directory))
            for corrupt in [store.iloc[:-1], store.assign(predicted_units=-1), store.assign(run_id="wrong"), pd.concat([store, store.iloc[:1]])]:
                corrupt.to_csv(directory/"store_daily_future_forecast.csv", index=False)
                refresh_manifest()
                with self.assertRaises(ValueError):
                    ns["verify_bundle"](directory)
            store.to_csv(directory/"store_daily_future_forecast.csv", index=False)
            tables["map_summaries.csv"].assign(total_units=1).to_csv(directory/"map_summaries.csv", index=False)
            refresh_manifest()
            with self.assertRaises(AssertionError):
                ns["verify_bundle"](directory)

    def test_store_runtime_legacy_and_insufficient_evidence(self):
        cell = next(c for c in nb["cells"] if "store_forecast" in c["metadata"].get("tags", []))
        area_forecast = ns["predict_seven"]("last_week", None, self.panel, self.cutoff)
        scope = dict(ns, transactions=self.tx, coverage=self.cov, blocked_groups=self.blocked,
                     cutoff=self.cutoff, as_of=self.as_of, evaluation={"limitations":["test"]},
                     MODE="forecast_only", DATA_KIND="real", panel=self.panel, forecast=area_forecast,
                     SAVED_STORE_MODEL_PATH=None, COORDINATES_PATH=None, display=lambda *args:None)
        exec(compile(cell["source"], cell["id"], "exec"), scope)
        self.assertEqual(len(scope["store_statuses"]), 18)
        self.assertTrue(scope["store_statuses"].status.eq("saved_store_model_unavailable").all())
        self.assertTrue(scope["store_forecast"].empty)
        self.assertTrue(scope["coordinates"].empty)
        pd.testing.assert_frame_equal(area_forecast, scope["forecast"])
        end = self.panel.date.min()+pd.Timedelta(days=59)
        scope.update(MODE="train", cutoff=end, as_of=ns["issuance_time"](end),
                     history=self.panel.iloc[:0], published_method="last_week", estimator=None)
        exec(compile(cell["source"], cell["id"], "exec"), scope)
        self.assertIsNone(scope["store_method"])
        self.assertTrue(scope["store_statuses"].status.eq("insufficient_store_evaluation").all())
        self.assertTrue(scope["store_forecast"].empty)
        self.assertIn("84", scope["store_evaluation"]["message"])


def execute_notebook():
    """Execute actual cells locally, no IPython kernel; first test train then inference."""
    import os
    import shutil
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with workspace_temp() as temp:
        original = Path.cwd()
        os.chdir(temp)
        try:
            shutil.copyfile(NOTEBOOK, Path(temp)/NOTEBOOK.name)
            scope = {"display":lambda *args, **kwargs:None}
            for cell in nb["cells"]:
                if cell["cell_type"] != "code" or "setup" in cell["metadata"].get("tags", []):
                    continue
                exec(compile(cell["source"], str(NOTEBOOK), "exec"), scope)
                if "config" in cell["metadata"].get("tags", []):
                    scope.update(DEMO_PRESET=None, GENERATE_DEMO=True, FORECAST_CUTOFF="2026-11-01", MODEL_TREES=20,
                                 SMOKE_RUN=True, SHOW_DASHBOARD=False)
            model_path = (scope["run_dir"]/"method.joblib").resolve()
            store_model_path = (scope["run_dir"]/"store_method.joblib").resolve()
            assert scope["verify_bundle"](scope["run_dir"])
            assert len(scope["forecast"]) == 42
            assert len(scope["store_forecast"]) == 126
            assert "What this run tells you" in (scope["run_dir"]/"run_report.md").read_text(encoding="utf-8")
            for name in ["area_candidates", "store_candidates"]:
                assert set(scope[name].method) == set(ns["TREE_METHODS"])
            # Exercise real Folium HTML generation without a browser or notebook kernel.
            for view in ["historical", "forecast"]:
                map_object, rows = scope["demand_map"](scope["map_summary"], scope["coordinates"], scope["area_labels"],
                    ns["ALL_CATEGORIES"], view, 90, scope["panel"].iloc[0].area_id, "synthetic")
                assert "leaflet" in map_object.get_root().render().lower()
                assert len(rows) == 3
            before = scope["forecast"].predicted_units.to_numpy().copy()
            store_before = scope["store_forecast"].predicted_units.to_numpy().copy()
            scope.update(MODE="forecast_only", GENERATE_DEMO=False, SAVED_MODEL_PATH=model_path,
                         SAVED_STORE_MODEL_PATH=store_model_path, FORECAST_CUTOFF="2026-10-31")
            for cell in nb["cells"]:
                if cell["cell_type"] == "code" and set(cell["metadata"].get("tags", [])) & {"load","observations","evaluate","forecast","store_forecast","report","preview","summary","export"}:
                    exec(compile(cell["source"], str(NOTEBOOK), "exec"), scope)
            assert np.allclose(before, scope["forecast"].predicted_units)
            assert np.allclose(store_before, scope["store_forecast"].predicted_units)
            assert scope["area_candidates"].empty and scope["store_candidates"].empty
            assert scope["verify_bundle"](scope["run_dir"])
            assert "No new model comparison or accuracy measurement" in (scope["run_dir"]/"run_report.md").read_text(encoding="utf-8")
            # Widget callbacks must redraw selections without fitting any model.
            scope["fit_method"] = lambda *a, **k: (_ for _ in ()).throw(AssertionError("Filter retrained a model"))
            preview = scope["dashboard_preview"](scope["panel"], scope["forecast"], scope["store_panel"], scope["store_forecast"],
                scope["map_summary"], scope["coordinates"], scope["area_labels"], scope["cutoff"], "synthetic",
                scope["published_method"], scope["store_method"], scope["validation_predictions"], scope["comparison"],
                scope["area_candidates"], scope["store_result"], scope["store_candidates"])
            for control, attribute, value in [("period", "value", 180), ("tabs", "selected_index", 1),
                ("scope", "value", "store"), ("category", "value", "demo-category-0"),
                ("area", "value", scope["panel"].area_id.unique()[-1]), ("comparisons", "value", True)]:
                setattr(preview[control], attribute, value)
                preview["refresh"]()  # Surface errors that a widget observer might otherwise capture.
            plt.close("all")
            print("TRAIN + FORECAST_ONLY CELL EXECUTION AND BUNDLE VERIFICATION PASSED")
        finally:
            os.chdir(original)


if __name__ == "__main__":
    execute = "--execute" in sys.argv
    if execute:
        sys.argv.remove("--execute")
    result = unittest.main(exit=False, verbosity=2)
    if not result.result.wasSuccessful():
        sys.exit(1)
    if execute:
        execute_notebook()
