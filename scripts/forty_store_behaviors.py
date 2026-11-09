"""Documented fictional events for the second forty-store experiment.

These events modify synthetic sales generation only. They are not notebook features.
"""
from datetime import date, timedelta
import random

ZIP_NAME = "Bale_Backend_Messy_40_Stores_Behavior_V2_Inputs.zip"
PROFILE = "messy-forty-stores-behavior-v2"


def assign_behaviors(groups, excluded, end, seed):
    available = [key for key in groups if key not in excluded]
    if len(available) < 60:
        raise ValueError("The behavior experiment needs 60 combinations outside the cleaning/reporting targets.")
    random.Random(seed+987).shuffle(available)
    events = {}
    for i,key in enumerate(available[:20]):
        first = end-timedelta(days=62 if i<10 else 13)
        events[key] = {"behavior":"promotion","start":first.isoformat(),
                       "end":(first+timedelta(days=6)).isoformat(),"multiplier":2.0}
    for i,key in enumerate(available[20:40]):
        events[key] = {"behavior":"level_shift","start":(end-timedelta(days=27)).isoformat(),
                       "end":end.isoformat(),"multiplier":1.7 if i<10 else .5}
    for key in available[40:60]:
        events[key] = {"behavior":"intermittent","start":(end-timedelta(days=179)).isoformat(),
                       "end":end.isoformat(),"active_day_probability":.35}
    return events


def weight_multiplier(event, day):
    if event and date.fromisoformat(event["start"]) <= day <= date.fromisoformat(event["end"]):
        return event.get("multiplier",1.)
    return 1.


def behavior_documentation(manifest):
    behaviors = manifest["sales_behaviors"]
    examples = []
    for behavior in ["promotion","level_shift","intermittent"]:
        selected = [row for row in behaviors["events"] if row["behavior"] == behavior][:3]
        examples += [f"- {row['barangay']} / {row['category_name']} / store {row['store_id']}: {behavior}, {row['start']} to {row['end']}." for row in selected]
    return f"""

## How version 2 differs from the previous forty-store ZIP

The same stores, barangays, products, categories, dates, 200,000-row budget, and
cleaning counts are retained. Sales are newly generated with seed {manifest['seed']}
and a distinct transaction-ID prefix. Existing files were not replaced.

- **Temporary promotions:** ten store/category combinations receive double their
  normal sales-generation weight during September 7-13; ten others during
  October 26-November 1. Their event multipliers return to one afterward.
- **Sudden changes from October 12:** ten combinations receive 1.7 times their
  normal generation weight and ten receive half, through November 8.
- **Irregular activity:** twenty other combinations have a 35% daily chance of
  activity. Inactive dates are fully reported zero-sale days, not missing data.
- Remaining combinations retain varied weekday patterns, noise, gradual changes,
  and occasional bulk purchases. Cleaning and reporting targets have moved to
  other store/category combinations; they do not overlap the sixty behavior cases.

Dates above describe the delivered default period. Exact schedules for any
regenerated period are recorded in dataset_manifest.json.

The fixed overall budget redistributes sale lines across combinations and dates.
Multipliers affect generation probabilities: recorded quantities need not double
exactly during a promotion. Random fluctuations and package quantities still vary.

### A few places to inspect in your charts

{chr(10).join(examples)}

Full event lists and measured line counts are in the manifest's sales_behaviors
section. These are known fictional causes in the experiment; the notebook does
not receive these event labels as model inputs. A feature-usage score or forecast
change cannot independently prove a real-world cause.

Slow-selling combinations may correctly be withheld by the notebook's existing
sales-activity requirements. Read actual eligibility counts rather than expecting
the first dataset's exact forecast-row count. No model is forced to win, and
synthetic results do not establish real customer-sales accuracy.
"""
