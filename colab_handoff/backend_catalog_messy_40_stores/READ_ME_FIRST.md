# Forty-store messy dataset: use your existing notebook

Use **Bale_Backend_Demo_Colab.ipynb** without editing it. Start a fresh Colab runtime
(Disconnect and delete runtime, then reconnect), select Run all, and upload
**Bale_Backend_Messy_40_Stores_Inputs.zip** when prompted. No new notebook is supplied or required.

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

- A. O. Floirendo / Rice and Grains / store 1000000000
- Datu Abdul Dadia / Rice and Grains / store 1000000004
- Buenavista / Rice and Grains / store 1000000008
- Cacao / Rice and Grains / store 1000000012

These combinations have invalid/conflicting records and should be withheld. Other
stores can still have their own forecasts, but the area total for the affected
category cannot be complete, so the affected area/category forecast is withheld too.

## Partial reporting on 2026-11-08

- Cagangohan / Drinks / store 1000000016
- Consolacion / Drinks / store 1000000020
- Dapco / Drinks / store 1000000024
- Gredu / Drinks / store 1

One contributor with unknown sales prevents a complete area/category total. Missing
sales remain unknown, not zero. Other combinations still need to pass eligibility.

## Historical reporting delays

- A. O. Floirendo / Snacks / store 1000000003
- Datu Abdul Dadia / Snacks / store 1000000007
- Buenavista / Snacks / store 1000000011
- Cacao / Snacks / store 1000000015

On 2026-08-16, 2026-08-30, these stores' sales and reporting
statements arrive two days after the event, rather than the following morning.
Earlier forecasts cannot use them; eligible counts can change between test weeks.

All quantities and reporting statements are hypothetical. Different package sizes
are not converted into equivalent consumption. Model rankings show performance on
this generated experiment, not demonstrated accuracy on real customer sales.
Scenario details and expected counts are also inside dataset_manifest.json.
