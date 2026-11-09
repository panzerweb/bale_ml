# Forty-store messy dataset: use your existing notebook

Use **Bale_Backend_Demo_Colab.ipynb** without editing it. Start a fresh Colab runtime
(Disconnect and delete runtime, then reconnect), select Run all, and upload
**Bale_Backend_Messy_40_Stores_Behavior_V2_Inputs.zip** when prompted. No new notebook is supplied or required.

## Dataset

200,000 sale lines across 40 stores, ten Panabo barangays, and seven categories.
Exactly four stores per barangay. History: 2026-05-13 through 2026-11-08.
Forecast: 2026-11-09 through 2026-11-15.
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

- Cacao / Health and Beauty / store 1000000015
- Cagangohan / Health and Beauty / store 1000000019
- Consolacion / Health and Beauty / store 1000000023
- Dapco / Health and Beauty / store 1000000027

These combinations have invalid/conflicting records and should be withheld. Other
stores can still have their own forecasts, but the area total for the affected
category cannot be complete, so the affected area/category forecast is withheld too.

## Partial reporting on 2026-11-08

- Gredu / Household / store 1000000030
- San Francisco / Household / store 1000000033
- Santo Niño / Household / store 1000000036
- A. O. Floirendo / Household / store 1000000003

One contributor with unknown sales prevents a complete area/category total. Missing
sales remain unknown, not zero. Other combinations still need to pass eligibility.

## Historical reporting delays

- Datu Abdul Dadia / Gadgets / store 1000000007
- Buenavista / Gadgets / store 1000000011
- Cacao / Gadgets / store 1000000015
- Cagangohan / Gadgets / store 1000000019

On 2026-08-23, 2026-09-06, these stores' sales and reporting
statements arrive two days after the event, rather than the following morning.
Earlier forecasts cannot use them; eligible counts can change between test weeks.

All quantities and reporting statements are hypothetical. Different package sizes
are not converted into equivalent consumption. Model rankings show performance on
this generated experiment, not demonstrated accuracy on real customer sales.
Scenario details and expected counts are also inside dataset_manifest.json.


## How version 2 differs from the previous forty-store ZIP

The same stores, barangays, products, categories, dates, 200,000-row budget, and
cleaning counts are retained. Sales are newly generated with seed 20261110
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

- Consolacion / Rice and Grains / store 1000000023: promotion, 2026-09-07 to 2026-09-13.
- Cagangohan / Snacks / store 1000000016: promotion, 2026-09-07 to 2026-09-13.
- A. O. Floirendo / School and Office / store 1000000001: promotion, 2026-09-07 to 2026-09-13.
- Datu Abdul Dadia / School and Office / store 1000000006: level_shift, 2026-10-12 to 2026-11-08.
- A. O. Floirendo / Gadgets / store 1000000002: level_shift, 2026-10-12 to 2026-11-08.
- A. O. Floirendo / Rice and Grains / store 1000000000: level_shift, 2026-10-12 to 2026-11-08.
- Cagangohan / Drinks / store 1000000019: intermittent, 2026-05-13 to 2026-11-08.
- Consolacion / Gadgets / store 1000000021: intermittent, 2026-05-13 to 2026-11-08.
- Cagangohan / Snacks / store 1000000018: intermittent, 2026-05-13 to 2026-11-08.

Full event lists and measured line counts are in the manifest's sales_behaviors
section. These are known fictional causes in the experiment; the notebook does
not receive these event labels as model inputs. A feature-usage score or forecast
change cannot independently prove a real-world cause.

Slow-selling combinations may correctly be withheld by the notebook's existing
sales-activity requirements. Read actual eligibility counts rather than expecting
the first dataset's exact forecast-row count. No model is forced to win, and
synthetic results do not establish real customer-sales accuracy.
