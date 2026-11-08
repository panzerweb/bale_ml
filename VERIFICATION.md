# Panabo city dataset verification — November 9, 2026

The default notebook preset is now `panabo_50k`. Delivered files are in
`demo_data/panabo_50k/`; reproduction and usage are described in that folder's README.

- Exactly 50,000 completed synthetic sale lines across 40 PSA-identified barangays,
  80 fictional stores, four categories, and eight fictional products.
- Exactly 180 Philippine dates, May 13–November 8, 2026. Preset issuance is
  `2026-11-09T00:15:00+08:00`, with the requested cutoff preserved. Baseline dates
  are November 9–15; no forecasts are inserted into the historical CSV.
- 57,600 coverage statements and store/category/day observations; 28,800
  barangay/category/day observations. Both observation levels reconcile with the
  87,385 recorded units in the sale lines. No missing days are disguised as sales.
- Unique sale-line identities, valid catalog/store references, positive quantities,
  next-day known-at timestamps, and no quarantined or duplicate rows.
- All series meet existing eligibility checks at the final cutoff and every
  validation, reserved-calibration, and final-evaluation issuance cutoff.
- Exact regeneration of all eight CSVs and the manifest, checksum-tamper rejection,
  custom 90-day generation, and rejected insufficient row/history budgets.
- Approximate reference coordinates and per-row source URLs for all 40 barangays.
  Coordinate parsing supports missing paired values without dropping analytical
  totals. Points are sourced references, not claimed store locations or official centroids.
- The notebook embeds the canonical standard-library generator and geographic
  snapshot; `scripts/sync_panabo_notebook.py --check` verifies they match the sources.
- The full-city last-week baseline produces 1,120 area/category forecast rows.
  Historical 90/180-day and seven-day forecast summaries cover all 40 areas and
  four categories plus their explicitly mixed-package totals.

Validation commands: `python tests/test_panabo_data.py` (eight tests),
`python tests/test_notebook.py` (the existing 21 tests), and
`python scripts/sync_panabo_notebook.py --check`. Python and notebook code syntax
were also checked. **All 29 tests passed**, and the embedded-source check passed.
The original small demo and its evaluation/refusal tests are retained.

To support the larger profile, canonical locations are computed once per distinct
label pair, and daily observations use grouped inputs rather than scanning the
entire transaction and coverage tables for every series. Forecast selection and
temporal rules are unchanged.

**Execution limit:** the available system Python has NumPy and pandas, but lacks
Matplotlib, scikit-learn, XGBoost, LightGBM, Folium, ipywidgets, and joblib. Installing
the missing dependencies from PyPI failed with “No matching distribution found.”
Consequently no full tree-model training, new model accuracy score, rendered map,
interactive widget, or Colab execution is claimed for the city dataset. Run the
notebook in a Colab environment with package access to verify those displays and
complete training. The full-city data tests exercise the actual notebook cleaning,
coverage, observation, eligibility, baseline prediction, and map-summary functions.

The earlier verification record below describes the smaller fixture.

# Verification record

Verified locally on 2026-11-08 with Python 3.13 and the available pandas/NumPy installation.

## Passed

Command: `python tests/test_notebook.py`

All **21 tests passed** after adding the demand preview and store pipeline. Tests execute functions and runtime cells extracted from the deliverable notebook, rather than a separate implementation. Coverage includes:

- Notebook JSON structure and Python syntax for every code cell.
- Deterministic 180-day synthetic input generation: 3,236 sale lines, three areas, six area/category series, and 1,080 daily observations.
- Area-prefix/alias merging and separate identities for identically named barangays in different cities.
- Leading-zero identifiers, exact duplicates, conflicting duplicates, invalid timestamps/statuses/quantities, unit normalization, unsupported identities, and missing columns.
- Reporting gaps and uncovered groups remain unknown/withheld; all-zero, sparse, and short histories are handled explicitly.
- Shared training/inference feature calculations and the 28-day warmup.
- Changes to future quantities, late-known rows, and future conflict evidence cannot affect earlier-cutoff baseline forecasts.
- The 180-day and 90-day chronological protocols with both baselines: 1,008 scored rows in total across the two test fixtures. Synthetic scores establish code behavior only.
- Zero-denominator WAPE remains unavailable.
- Export integrity verification rejects tampered files and incomplete seven-day sequences, and accepts an empty forecast accompanied by refusal statuses.
- Store-level observations: 18 store/category series and 3,240 daily observations, reconciling to the six area/category series. A reporting gap in one store does not invalidate unrelated stores.
- Store feature warmup/parity, future/late-known data isolation, store-specific and area-wide quarantine propagation, and changed/new saved-model identities.
- Independent store baseline evaluation across four validation and four final issuance windows, with 1,008 validation rows and 504 final rows for the selected baseline in this fixture. No tree-model accuracy is claimed.
- Exact inclusive 90/180-day map windows, strict mixed-category totals, confirmed zero totals, incomplete periods, and missing category forecasts.
- Coordinate ranges, paired missing coordinates, conflicting coordinate identities, and explicit synthetic sources.
- Additive dashboard bundle verification rejects invalid store quantities, duplicates, mismatched run IDs, incomplete sequences, and inconsistent map totals even when checksums are recomputed.
- Actual store runtime cells with a legacy area-only inference setup withhold store forecasts, and insufficient store evaluation evidence withholds that scope without aborting area results.

Generated verification fixtures are isolated and cleaned up after tests. The notebook is delivered without execution outputs or invented metrics.

## Not verified in this environment

The local environment lacks scikit-learn, XGBoost, LightGBM, joblib, Matplotlib, ipywidgets, Folium, and Jupyter execution tools. Package installation failed: the default package index is disabled, an explicit PyPI attempt yielded no distributions, and the relevant cached wheels contain only NumPy and pandas. No external approval or access change was requested.

Consequently, **full tree-model comparison, actual joblib reload parity, train-to-forecast-only execution, interactive widget/map rendering, and execution inside Google Colab have not been verified**. No trained model, rendered chart result, or full training result is delivered or claimed. The notebook remains self-contained and is saved without execution outputs.

`python tests/test_notebook.py --execute` was attempted: the then-current 20 data tests passed, followed by `ModuleNotFoundError: No module named 'matplotlib'` at the execution stage. The final 21-test suite adds the legacy/insufficient-store-evidence runtime case. Syntax checks pass for all 16 code cells in the 27-cell notebook.

The notebook contains runtime reload-parity and bundle checks. Once its dependencies are available, run:

```text
python tests/test_notebook.py --execute
```

That command first runs the 21 checks, then executes the actual notebook cells in a temporary workspace with a synthetic dataset and 20-tree smoke configuration. It exercises both forecast scopes, saved-method reload, forecast-only mode, export verification, Folium HTML generation, and widget callbacks that must not retrain. It does not use a Jupyter kernel or establish Colab-specific compatibility. The default notebook comparison uses 120 trees; a smoke run is separately labeled.

For a Colab check, open the notebook, set `GENERATE_DEMO=True` and `SHOW_DASHBOARD=True`, and run all cells. Exercise both tabs, both lookbacks, All categories and each category, barangay/store selectors, and the notebook-only model diagnostics. Confirm that selections change displays without fitting and that synthetic coordinate labels remain visible. Then test real inputs separately after reviewing their reporting evidence and source reconciliation, including a supplied coordinate sidecar and an area without coordinates. Synthetic success cannot establish real forecast accuracy. The actual seller application is maintained in a separate repository and was not changed here.
