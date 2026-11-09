"""Version 2 integration and event scheduling, with the real notebook pipeline."""
from collections import Counter
from datetime import date,timedelta
import sys
import unittest

import test_messy_forty_stores as baseline
from forty_store_behaviors import ZIP_NAME,assign_behaviors,weight_multiplier


class BehaviorV2Tests(baseline.FortyStoreTests):
    profile = "forty_stores_behavior_v2"
    zip_name = ZIP_NAME

    def test_affected_area_totals_withheld_while_other_stores_remain_eligible(self):
        scenarios = self.manifest["intentional_scenarios"]
        targets = scenarios["corrupt_store_categories"]+scenarios["partial_store_categories"]
        for scope,fields in [("GROUP",["area_id","category_id"]),("STORE_GROUP",["store_id","area_id","category_id"])]:
            expected = {tuple(r[k] for k in fields) for r in targets}
            statuses = self.ns["eligibility"](self.panels[scope],self.cutoff,self.ns[scope])
            actual = set(statuses.loc[statuses.status.ne("eligible"),fields].itertuples(index=False,name=None))
            self.assertTrue(expected <= actual)
        statuses = self.ns["eligibility"](self.panels["STORE_GROUP"],self.cutoff,self.ns["STORE_GROUP"])
        for row in scenarios["corrupt_store_categories"]:
            others = statuses.loc[statuses.area_id.eq(row["area_id"]) & statuses.category_id.eq(row["category_id"]) & statuses.store_id.ne(row["store_id"])]
            self.assertTrue(others.status.eq("eligible").any())

    def test_event_assignments_are_disjoint_from_quality_targets(self):
        events = self.manifest["sales_behaviors"]["events"]
        self.assertEqual(Counter(r["behavior"] for r in events),{"promotion":20,"level_shift":20,"intermittent":20})
        keys = {(r["store_id"],r["category_id"]) for r in events}
        self.assertEqual(len(keys),60)
        scenarios = self.manifest["intentional_scenarios"]
        targets = scenarios["corrupt_store_categories"]+scenarios["partial_store_categories"]+scenarios["late_store_categories"]
        self.assertFalse(keys & {(r["store_id"],r["category_id"]) for r in targets})
        self.assertEqual(self.manifest["sales_behaviors"]["ordinary_combinations"],215)
        self.assertFalse(self.manifest["sales_behaviors"]["used_as_model_features"])
        self.assertNotIn("behavior",self.raw.columns)
        self.assertEqual(self.manifest["seed"],20261110)
        self.assertTrue(self.raw.transaction_id.str.startswith("messy40b:20261110:").all())

    def test_promotion_dates_and_return_to_normal(self):
        events = [e for e in self.manifest["sales_behaviors"]["events"] if e["behavior"] == "promotion"]
        self.assertEqual(Counter((e["start"],e["end"]) for e in events),{
            ("2026-09-07","2026-09-13"):10,("2026-10-26","2026-11-01"):10})
        for event in events:
            first,last = date.fromisoformat(event["start"]),date.fromisoformat(event["end"])
            self.assertEqual(weight_multiplier(event,first-timedelta(days=1)),1.)
            self.assertEqual(weight_multiplier(event,first),2.)
            self.assertEqual(weight_multiplier(event,last),2.)
            self.assertEqual(weight_multiplier(event,last+timedelta(days=1)),1.)
            self.assertEqual(event["realized_event_days"],7)
        # Inspect the actual, accepted sale lines across all simulated campaigns.
        during,before = 0,0
        for event in events:
            first,last = self.pd.Timestamp(event["start"]),self.pd.Timestamp(event["end"])
            g = self.tx.loc[self.tx.store_id.eq(event["store_id"]) & self.tx.category_id.eq(event["category_id"])]
            actual = len(g.loc[g.date.between(first,last)])
            self.assertEqual(actual,event["realized_event_sale_lines"])
            during += actual
            before += len(g.loc[g.date.between(first-self.pd.Timedelta(days=7),first-self.pd.Timedelta(days=1))])
        self.assertGreater(during,before)

    def test_level_shifts_and_genuine_intermittent_zero_days(self):
        events = self.manifest["sales_behaviors"]["events"]
        shifted = [e for e in events if e["behavior"] == "level_shift"]
        self.assertEqual(Counter(e["multiplier"] for e in shifted),{1.7:10,.5:10})
        for event in shifted:
            self.assertEqual(event["start"],"2026-10-12")
            self.assertEqual(weight_multiplier(event,date(2026,10,11)),1.)
            self.assertEqual(weight_multiplier(event,date(2026,10,12)),event["multiplier"])
            self.assertEqual(weight_multiplier(event,date(2026,11,8)),event["multiplier"])
        parameters = {(r["store_id"],r["category_id"]):r for r in self.manifest["intentional_scenarios"]["parameters"]}
        for event in [e for e in events if e["behavior"] == "intermittent"]:
            key = (event["store_id"],event["category_id"])
            self.assertAlmostEqual(parameters[key]["zero_activity_probability"],.65)
            panel = self.panels["STORE_GROUP"]
            g = panel.loc[panel.store_id.eq(key[0]) & panel.category_id.eq(key[1])]
            self.assertTrue(g.observation_status.eq("complete").all())
            self.assertTrue(g.units_sold.eq(0).any())
            self.assertGreater(g.units_sold.eq(0).mean(),.4)

    def test_new_scenario_targets_and_repeatable_assignment(self):
        scenarios = self.manifest["intentional_scenarios"]
        self.assertEqual({r["category_id"] for r in scenarios["corrupt_store_categories"]},{"4"})
        self.assertEqual({r["category_id"] for r in scenarios["partial_store_categories"]},{"5"})
        self.assertEqual({r["category_id"] for r in scenarios["late_store_categories"]},{"6"})
        self.assertEqual(scenarios["late_reporting_dates"],["2026-08-23","2026-09-06"])
        keys = [(str(i),"1") for i in range(80)]
        a = assign_behaviors(keys,set(keys[:3]),date(2026,11,8),20261110)
        self.assertEqual(a,assign_behaviors(keys,set(keys[:3]),date(2026,11,8),20261110))
        self.assertNotEqual(a,assign_behaviors(keys,set(keys[:3]),date(2026,11,8),20261111))


if __name__ == "__main__":
    unittest.main(verbosity=2)
