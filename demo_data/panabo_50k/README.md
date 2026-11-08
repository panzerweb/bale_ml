# Panabo city synthetic sales dataset

**50,000 sale lines · 40 barangays · 80 fictional stores · four categories**

History covers **May 13–November 8, 2026**, inclusive (180 complete Philippine dates).
The configured forecast is **November 9–15, 2026**, issued at 00:15 Manila on November 9.
Sales and reporting history are simulated. They do not describe actual Panabo business activity.

## Open the visualization

Open `Panabo_Area_Demand_Forecastingg.ipynb` from the project root in Jupyter or Google
Colab and run all cells. The default `DEMO_PRESET="panabo_50k"` loads this folder, or
generates the same data when the folder is absent. The generator and reference snapshot
are embedded, so uploading only the notebook to Colab is sufficient. The setup cell
installs missing ML/plotting libraries where package downloads are available.

After training, use the existing **Historical Demand** and **Forecast Demand** tabs,
90/180-day history selector, category and barangay filters, and individual-store view.
The expandable experiment diagnostics compare the candidate models. Every output stays
labeled synthetic. Training selects a method through the existing chronological evaluation;
the dataset does not promise a particular winning model or accuracy score.

To use real inputs, set `DEMO_PRESET=None` and `GENERATE_DEMO=False`, then configure
your CSV, coverage, coordinates, time settings, and data kind. To use the old small
fixture, set `DEMO_PRESET=None` and `GENERATE_DEMO=True`.

## Files

| File | Rows | Use |
|---|---:|---|
| `transactions.csv` | 50,000 | Notebook input: one completed sale line per row, existing 15-column schema |
| `coverage.csv` | 57,600 | Notebook input: one complete store/category/day reporting statement |
| `areas.csv` | 40 | PSA barangay identities, approximate reference coordinates, and source URLs |
| `stores.csv` | 80 | Two fictional stores per barangay; no claimed real store coordinates |
| `categories.csv` | 4 | Readable categories, recorded units, and standardized package sizes |
| `products.csv` | 8 | Two fictional products per category with consistent packaging |
| `area_daily_observations.csv` | 28,800 | Supplemental barangay/category/day totals for quick analysis |
| `store_daily_observations.csv` | 57,600 | Supplemental store/category/day totals, including reported zero sales |
| `dataset_manifest.json` | — | Parameters, assumptions, time boundaries, counts, and SHA-256 checksums |

The notebook recomputes observations from transactions and coverage. Supplemental daily
CSVs are conveniences, not additional training inputs. Forecasts are produced by the
notebook and are not fabricated in the historical dataset.

## How the data was simulated

Seed `42` controls arbitrary area/store differences, category weights, weekday effects,
modest trends, quantity noise, products, sale times, and sales channels. Geographic
coordinates and population are not predictors of the generated activity. Each store
sells all four categories throughout the period. A reserved positive-sale day every
four dates ensures at least seven positive dates in any complete 28-day window;
remaining sale lines are weighted random draws. This is a disclosed demonstration
constraint, not evidence about real store activity.

Coverage assumes every store is open and reports completely every day. A no-sale day
therefore has zero recorded units; stock availability remains unknown. Every sale and
coverage statement becomes known at 00:05 the following Philippine day, before the
00:15 forecast issuance. Neither the incomplete November 9 date nor future sales enter
the historical inputs.

Beverages use 500 mL bottles, snacks 30 g packs, canned goods 155 g cans, and instant
noodles 55 g packs. A recorded unit is one such package. Combined category totals count
mixed packages, not equivalent physical consumption. Prices, customer identities,
weather, holidays, and actual local events are not invented as historical evidence.

## Geographic references

Barangay names and 10-digit PSGC codes come from the
[PSA Panabo directory](https://psa.gov.ph/classification/psgc/barangays/1102315000).
That directory displays its roster as of July 31, 2025; it was checked on November 9,
2026. The reference snapshot is preserved in `data/panabo_reference.json`.

Coordinates are published approximate reference points from each barangay's
[PhilAtlas profile](https://www.philatlas.com/mindanao/r11/davao-del-norte/panabo.html).
Every row records its exact source URL. These are not official centroids, surveyed
boundaries, or participating-store positions. All 40 currently have sourced points;
the notebook also supports paired blank coordinates and retains their analytical totals.

## Regenerate and verify

From the project root:

```powershell
python scripts/generate_panabo.py --rows 50000 --days 180 --end-date 2026-11-08 --seed 42 --output demo_data/panabo_50k
python tests/test_panabo_data.py
python tests/test_notebook.py
```

Generation needs only the Python standard library. Notebook/data integration tests need
NumPy and pandas; full model and dashboard execution needs the notebook dependencies.
The same generator version, reference snapshot, and parameters reproduce identical CSVs
and the same manifest. The generator rejects fewer than 84 historical dates or a row
budget below its activity floor (14,400 rows for this 180-day profile).

For a full smoke execution after dependencies are installed:

```powershell
python tests/test_notebook.py --execute
```

That uses the smaller existing fixture with 20-tree models. The large dataset's
cleaning, reconciliation, activity eligibility, baseline forecasting, and map-summary
windows have separate checks in `tests/test_panabo_data.py`. Full city training and
interactive display should also be checked in Colab; see `VERIFICATION.md` for what
was actually executable locally.
