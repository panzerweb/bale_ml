# App → model → app: first run and recurring workflow

For a new backend developer's device, start with the
[backend setup and API runthrough](BACKEND_RUNTHROUGH.md). It covers cloning both
repositories, local Docker configuration, Colab handoff, import/activation,
store-token testing, and files that are not transferred by Git.

For a standalone synthetic run tied to existing backend logins, use
`python scripts/prepare_backend_colab.py` after the backend's read-only
`market-demand-export-catalog` command has supplied `inputs/backend_catalog.json`.
This creates `colab_handoff/backend_catalog_demo/` with a configured notebook,
an input ZIP, backend identity/unit mappings for the later import, and
`START_HERE.md`. Upload the configured notebook in Colab, Run all, then select
the input ZIP when prompted. No training sales are inserted into the database.
The canonical notebook's model functions are preserved. This profile covers
only the stores/categories actually present in the exported catalog; the
full-city preset described below is a separate demonstration. Generated sales
remain synthetic even though the catalog IDs and names come from the backend.

This repository prepares and evaluates forecasts in Google Colab and includes an interactive demand preview. The backend and application are maintained in their separate repository. The notebook exports files for that team; it does not implement their importer or API.

The notebook now starts with `DEMO_PRESET="panabo_50k"`: **50,000 synthetic sale lines across all 40 Panabo barangays**, 80 fictional stores, and four categories. History covers May 13–November 8, 2026; the preset forecasts November 9–15. Run all cells to generate/load the inputs and open the existing dashboard. The generator and geographic reference snapshot are embedded for standalone Colab use. See [dataset details and regeneration commands](demo_data/panabo_50k/README.md).

For real inputs, set `DEMO_PRESET=None` and `GENERATE_DEMO=False` before following the real-data instructions below. The old small fixture remains available with `DEMO_PRESET=None` and `GENERATE_DEMO=True`.

The area forecast answers: **How many recorded sale units will participating stores in each city/barangay sell in a category over the next seven days?** A separate pipeline now estimates individual-store/category sales. Neither estimates total resident demand or recommends inventory purchases. Stockouts can suppress sales.

## 1. Prepare the first export

Export `transactions.csv` with one row per sale line and this exact header:

```csv
transaction_datetime,known_at,transaction_id,transaction_item_id,transaction_status,store_id,city,barangay,product_id,variant_id,category_id,quantity,unit_label,sales_channel
```

| Fields | Meaning and handling |
|---|---|
| `transaction_datetime` | When the completed sale happened, not when an order was created. Use an offset such as `2026-10-01T12:30:00+08:00`. |
| `known_at` | When this exported record/version became available to the system. A late offline sale must not enter an earlier forecast. Do not invent this timestamp. |
| Transaction/item/store/product/variant/category IDs | Stable strings. Leading zeros are preserved. Item IDs must identify real sale lines, not CSV row numbers. |
| `transaction_status` | Explicit source status. Only normalized `completed` sales enter the target. Review source-specific mappings before running. |
| `city`, `barangay` | Store location, not buyer address. Prefixes, casing, and spaces are normalized; reviewed spelling aliases merge labels within each city. |
| `quantity`, `unit_label` | Positive recorded quantity and its sellable unit. One pack remains one pack; no inferred contents conversion. |
| `sales_channel` | `pos` or `online`, after explicit alias mapping. This is provenance, not proof that the same economic sale was not exported twice. |

Check the source export for POS/online overlap. Different IDs do not prove two rows describe different sales. Monetary refunds do not establish returned item quantities. The notebook quarantines refunded rows and conflicting duplicates for reconciliation rather than inventing adjustments.

### Reporting coverage: zero is different from missing

A transaction CSV cannot prove that a day without transactions was a fully reported zero-sales day. Prefer an optional `coverage.csv`, **an input sidecar**, containing:

```csv
store_id,city,barangay,category_id,date,participation_status,reporting_status,operating_status,availability_status,known_at,coverage_source
```

Use `date` as `YYYY-MM-DD`, with one row per store/category/day. Alternatively supply the notebook's canonical `area_id` instead of city/barangay. Allowed values are:

- Participation: `active`, `not_started`, `ended`.
- Reporting: `complete`, `partial`, `unknown`.
- Operating: `open`, `closed`, `unknown`.
- Availability: `available`, `stockout`, `unknown`.

Include an offset `known_at` for the coverage statement and its evidence source. Missing statements stay unknown. Complete reporting on a closed day may support zero recorded sales; unknown reporting does not. Coverage is supplied evidence, not automatically verified by the notebook.

If only transactions are available, set all of `ASSUME_COMPLETE_REPORTING=True`, `REPORTING_START`, `REPORTING_END`, and `DECLARED_COHORT`. This declares which stores, areas, and categories reported throughout the range. For example:

```python
ASSUME_COMPLETE_REPORTING = True
REPORTING_START = "2026-05-01"
REPORTING_END = "2026-10-27"
DECLARED_COHORT = [
    {"store_id": "001", "city": "Panabo", "barangay": "Salvacion", "category_id": "010"},
]
```

This is an explicit assumption, not a way to recover absent reporting evidence. The report records the limitation. No additional file called `sales.csv` is required.

### How much history?

| Concept | Starting choice |
|---|---|
| Forecast horizon | Next seven dates |
| Recommended first historical span | At least 180 complete dates, where available |
| Shorter experiment | 84–179 calendar dates; 90 dates can qualify if reporting and sales activity are sufficient |
| Feature lookback | Previous 28 dates; lags at 1, 7, 14, 28 days |
| Group eligibility | At least 56 complete dates, the most recent 28 complete, and at least seven positive-sales dates in those 28 |

The minimum calendar span does not guarantee a group qualifies. The earliest 28 dates provide feature history and do not become training examples. A year or more is needed to examine annual patterns meaningfully; 180 dates do not establish annual seasonality or guarantee accuracy. Keep immutable exports; do not discard older data simply because the model uses 28-day features.

## 2. Run the first Colab training

1. Upload/open `Panabo_Area_Demand_Forecastingg.ipynb` in Colab. Use a CPU runtime.
2. For the full-city demonstration, keep `DEMO_PRESET="panabo_50k"`. It generates or checksum-validates the seeded inputs in `demo_data/panabo_50k/` and loads the barangay registry and sourced coordinate sidecar. The historical cutoff stays November 8, 2026, without the legacy demo's extra date subtraction. All sales and reporting results remain synthetic.
3. For real data, set `DEMO_PRESET=None`, leave `GENERATE_DEMO=False`, set `DATA_KIND="real"`, and upload the CSV. Set `COVERAGE_PATH` if available, or complete the reporting declarations above. Keep `AS_OF=None` for actual run time unless performing a documented historical replay.
4. Set `FORECAST_CUTOFF` to the last **complete reported** Manila date. Leaving it unset uses yesterday; it does not automatically mean yesterday's export is complete. `AS_OF` normally remains the actual run time.
5. Add reviewed aliases, for example `BARANGAY_ALIASES = {("Panabo", "Salvasion"): "Salvacion"}`. `Salvacion`, `Brgy. Salvacion`, and `Barangay Salvacion` already merge automatically. Optional `AREA_REGISTRY` supplies application area IDs and rejects unsupported locations. Without it, area IDs are internal hashes of normalized city/barangay names, not official geographic codes.
6. Keep `MODE="train"`, then choose **Runtime → Run all**. Review cleaning totals, quarantined groups, labels, unit mix, and coverage before accepting the run. Repair source problems or mappings and rerun when necessary.
7. Read the method comparison and plain-language report. A baseline winner is a valid result; do not adjust the final test until ML wins.
8. Download the results ZIP and your edited notebook before the temporary session ends.

The notebook has no dependency on this repository once uploaded. Its first cell installs missing scientific libraries. Save the run's dependency versions and edited notebook to reproduce it later; installed Colab versions can differ between sessions.

### Reading the results without a machine learning background

Each evaluation table now explains the result immediately afterward. **MAE decides the method**: it is the average number of recorded units missed per daily area/category (or store/category) prediction. RMSE gives larger misses more weight and can favor a different model. You do not need to choose between the charts. The notebook names the validation choice, explains the later check against the strongest simple alternative, and states which method actually generates the forecast.

Forecast previews include category names, column explanations, and a worked example from the current run. Empty prediction bounds are displayed as unavailable; this version does not calculate an uncertainty range. Every chart and map has reading guidance before it and observations afterward, including dashboard redraws. Feature usage describes inputs used by the selected model, not proven causes of sales changes.

Read **Your complete result, before export**, directly above **Versioned export and trusted model reload**, for the dataset, model rankings, selected method, forecast highlights, and practical limits together. This summary is also included in `run_report.md`. Saved-model refreshes explicitly distinguish original evaluation scores from new forecasts, which have not yet been checked against future actual sales.

The plain-language helpers live in `scripts/notebook_guidance.py`. After editing them, run `python scripts/sync_panabo_notebook.py`; use `--check` to verify the notebook's embedded copy. The notebook remains standalone. Regenerate configured backend demo notebooks with the existing handoff generator so they inherit these explanations.

### How evaluation works

For 180 dates, the first validation forecast uses days 1–96 and predicts days 97–103. Four validation weeks choose the method; four intervening weeks are reserved for future calibration work; four final weeks measure performance. For 84–179 dates, the last 28 dates contain two validation weeks and two final weeks. Earlier dates fit the method.

Each weekly cutoff is issued at **00:15 Manila the following day**. Only sales and reporting statements known then enter its history. The model predicts all seven dates recursively without reading outcomes within that week. Later windows may use earlier windows' outcomes once available. This evaluates weekly issuance with refitting, not a different daily-refresh schedule.

MAE is the average absolute daily group error in recorded units; RMSE emphasizes large errors; positive bias means overprediction; WAPE divides total absolute error by actual units and is unavailable when actual units sum to zero. The bundle also includes errors by group/horizon and complete-week totals. Missing outcomes and cohort changes are reported rather than scored as zeros.

Validation chooses among two simple baselines and three tree models. Final testing compares that choice with the strongest validation baseline. The declared release rule falls back to the baseline if selected ML does not improve final MAE. Report both results; the post-test choice has no new independent accuracy estimate. Prediction intervals are deliberately unavailable, not claimed as “90%.”

Current status and identity mappings may not reflect historical corrections, voids, or reclassifications. `known_at` filtering helps but does not reconstruct missing version history. Results are labeled retrospective current-state evaluation. Collect immutable source/coverage snapshots to improve operational replay.

## 3. Hand results to the backend team

Each run creates a fresh folder and ZIP under `ml_outputs/`. Preserve the complete bundle, but distinguish serving files from operator-only files:

| Artifact | Role |
|---|---|
| `daily_future_forecast.csv` | Seven daily forecasts per eligible area/category, run ID, recorded-unit policy, and empty unavailable bounds |
| `historical_observations.csv` | Actuals and observation status; unknown days remain gaps |
| `coverage_summary.csv`, `area_labels.csv`, `unit_mix.csv` | Eligibility/refusals, labels, and unit interpretation |
| `run_metadata.json` | Schema, method, dates, source fingerprints, dependencies, assumptions, and artifact checksums |
| `run_report.md`, evaluation files | Human explanation and measured experiment evidence |
| `method.joblib`, `history_state.csv` | Trusted Python inference assets; a model alone is insufficient |
| `area_coordinates.csv`, `map_summaries.csv` | Coordinate lookup and strict historical/forecast map totals, described below |
| `store_*` files | Private store forecasts, observations, eligibility, evaluation, and trusted inference assets |
| `candidate_future_forecasts.csv`, chart PNGs | Notebook experiment diagnostics; not the seller's selected forecast |
| Quarantine/duplicate files and contributor details | Private operator diagnostics, not public application downloads |

The backend team should validate the schema, IDs, checksums, nonnegative finite predictions, full seven-date sequences, data kind, and freshness before importing a new run. They must map internal area IDs to application identities if a registry was not supplied. Importing must preserve the previous valid run until the new snapshot is accepted. Those integration actions belong to the other repository.

The frontend reads backend-provided forecast data; it does not open `joblib`. Never deserialize an untrusted model file. Structured file validation does not make Python pickle loading safe. Cross-store publication/access controls remain the application team's responsibility.

## 4. What happens next?

```text
App records sales and reporting evidence
  → export an updated, reconciled history snapshot
  → clean and validate in Colab
  → refresh forecasts OR retrain and evaluate
  → export a new versioned bundle
  → backend validates/imports the snapshot
  → app displays the forecast
  → preserve the issued forecast and collect actual outcomes
  → compare errors/coverage and repeat
```

### Refresh a forecast without retraining

Use newer complete history, set `MODE="forecast_only"`, and set `SAVED_MODEL_PATH` to the trusted saved `method.joblib`. Upload compatible inputs and advance the cutoff. Include relevant historical coverage and transactions, with at least 56 complete dates and the latest 28 complete; uploading only today's new rows is insufficient. `history_state.csv` is a compact state export, not a replacement for the input validation history.

The saved model and canonical mappings remain fixed. The report preserves its original training date/evaluation and separately records the newer forecast cutoff and input fingerprint. New groups and changed cohorts are withheld until retraining. Forecast-only mode does not claim fresh accuracy measurement. A cutoff older than the model training end is rejected.

Daily refreshes can make forecasts fresher, but the notebook's scored training protocol is weekly refitting. Before relying on daily refresh quality, measure the actual issued forecasts from that schedule.

### Retrain and evaluate

Start with a manual **weekly retraining** review after complete reporting arrives. Use `MODE="train"` and a growing reconciled history export. Recompare the same candidates/baselines, review excluded groups, and hand off a new versioned bundle. More data does not automatically improve a model.

Preserve original forecasts when late sales or corrections arrive. Reconcile actuals using a documented reporting-close delay and measure error against the originally issued forecast, not a regenerated forecast. Review MAE/bias by category, area, horizon, and coverage. Investigate changing package mix, source overlap, reporting gaps, store openings, and stockouts before assuming model failure.

Do not repeatedly tune against the same final dates and call them untouched tests. After redesign, reserve new future dates for independent evidence. Declare real business error thresholds before looking at that final period. Review daily refresh versus weekly retraining frequency using measured freshness and errors; the starting schedule is an operational default.

If a run fails validation, retain the previous valid snapshot and surface its age. Do not replace missing forecasts with zero. Archive the input fingerprint, notebook/configuration, dependencies, evaluation, and previous bundle so the backend team can roll back.

## 5. Relationship to the reference documents

The files in `References/` remain unchanged as design history. This implemented notebook uses your smaller `transactions.csv` contract and makes Colab the primary path. Coverage is optional with an explicit assumption, auxiliary buyer/value features are removed, and uncertainty bounds are unavailable. The notebook preview now supports supplied representative coordinates and an All categories total of mixed recorded sale units; this supersedes the reference's single-category-only design for the preview. The reference's separate backend/frontend tasks are not implemented here.

For local verification, run `python tests/test_notebook.py`. Scientific dependency checks and notebook execution require the notebook's listed libraries. Local verification does not establish that a run has been executed inside Google Colab or that real predictive quality is acceptable.

## 6. Historical and forecast demand preview

The notebook installs Folium and ipywidgets alongside the scientific dependencies. Set `GENERATE_DEMO=True`, keep `SHOW_DASHBOARD=True`, and run all cells in Colab or Jupyter with widgets enabled. The default preview opens **Historical Demand**, **90** past days, **All categories**, and **Barangay** trend. Synthetic inputs and coordinates remain explicitly labeled.

- **Historical Demand** maps the total recorded sales over the last 90 or 180 dates, inclusive of the cutoff.
- **Forecast Demand** maps the published area method's next-seven-day total. The past-days selector changes chart context only; it never requests a 90/180-day forecast or retrains a model.
- The map shows all represented barangays for the chosen category and highlights the selected barangay. Numeric tooltips and the table provide exact totals. Heat smoothing does not locate demand on individual streets.
- Below the map, choose **Individual store** and a store ID to view that store's history and independently modeled forecast. The map continues to summarize barangays. Store predictions need not sum to the independently modeled barangay forecast.
- **All categories** sums recorded item counts. A pack and a bottle each remain one sellable unit; the combined number is labeled mixed sale units, not equivalent physical consumption. `__all_categories__` is the reserved aggregate selection identifier and cannot be a source category ID.
- Missing observations are gaps. A period with fewer than all requested complete days has an unavailable total. A combined forecast is unavailable if an applicable category lacks a full forecast; the preview does not silently publish a partial sum. History uses the cutoff's participating cohort, consistent with the existing pipeline.

An expandable **Notebook experiment diagnostics** section shows validation actual-versus-predicted panels for Random Forest, XGBoost, and LightGBM; validation MAE/RMSE bars for candidates and baselines; and the three candidates' next-seven-day forecasts. Bars summarize all eligible series in the selected scope; line charts follow the selected area/store/category. The published method is identified, including a baseline fallback. Only the validation-selected candidate and strongest validation baseline enter final evaluation. Diagnostic charts do not select a new winner.

For a script or smoke execution, set `SHOW_DASHBOARD=False`. Static diagnostics and structured exports are still generated in training mode. Forecast-only mode uses saved published models and explains why candidate comparisons are unavailable.

### Coordinate sidecar

For real data, set `COORDINATES_PATH=Path("areas.csv")` and supply:

```csv
area_id,latitude,longitude,coordinate_source
```

Use the canonical IDs in the notebook's area-label output, or configure `AREA_REGISTRY` before training. Supply one unambiguous row per area, finite latitude in [-90, 90], finite longitude in [-180, 180], and a nonempty source description. Both coordinates may be blank to explicitly withhold placement. Conflicting rows, unpaired coordinates, and invalid numbers are rejected. No geocoding is inferred from names.

Without supplied coordinates, sales still appear in charts and tables. The map explains missing placements. The Panabo city preset supplies published approximate barangay reference points with source URLs; these are not store locations or official centroids. The legacy small demo uses illustrative points. Interactive maps need access to their Leaflet assets and OpenStreetMap tiles.

### Store models and refreshes

Store observations use `(store_id, area_id, category_id, date)` and the same 56-complete-date / 28-recent-date / seven-positive-date eligibility checks. The store pipeline selects one pooled method across eligible store series, independently from area selection. It compares the same three tree methods and two baselines with the same temporal protocol. A store scope without sufficient evaluation evidence is withheld while an otherwise valid area run can still export.

Training exports `store_method.joblib` when evaluated store forecasts are available. For forecast-only runs, set `SAVED_STORE_MODEL_PATH` to that trusted file as well as the existing `SAVED_MODEL_PATH`. The store bundle must match cleaning mappings, data kind, feature version, and cutoff. New store/area/category identities and changed cohorts require retraining. Legacy area-only bundles still work: without a store bundle, store forecasts are explicitly unavailable.

### Additive artifact contract

The existing area forecast CSV columns and `market-demand-v1` contract remain unchanged. `run_metadata.json` adds `dashboard_version=market-demand-preview-v1`, store method/training provenance, an optional coordinate-input checksum, and a private store-artifact list. All emitted files join the checksum manifest and results ZIP.

| Artifact | Keys and meaning |
|---|---|
| `map_summaries.csv` | `(run_id, area_id, category_id, view, lookback_days)`; `view` is `historical` or `forecast`; historical lookback is 90/180, forecast lookback is 0. Includes explicit start/end dates, nullable `total_units`, `coverage_status`, complete/expected day counts, and applicable category count. |
| `area_coordinates.csv` | `area_id, latitude, longitude, coordinate_source`; missing coordinates do not suppress analytical totals. |
| `store_historical_observations.csv` | Store/area/category/date, recorded units, observation status, cohort, and store count. |
| `store_daily_future_forecast.csv` | Existing forecast fields plus `store_id`; seven dates per eligible store/area/category. |
| `store_coverage_summary.csv` | Store/area/category eligibility, refusal reason in `status`, complete-date count, and cohort. |
| `store_method.joblib`, `store_history_state.csv` | Trusted selected store model/configuration and recent state; private Python assets. |
| `store_evaluation_summary.json` | Independent store selection/final results, or the reason evaluated forecasts are unavailable. |
| `store_model_comparison.csv`, `store_backtest_predictions.csv`, `store_evaluation_refusals.csv` | Store experiment evidence, emitted after successful training/evaluation. |
| `candidate_future_forecasts.csv`, `store_candidate_future_forecasts.csv` | Diagnostic seven-day predictions with a `method` column; not published predictions. |

Blank CSV totals mean unavailable, never zero. `coverage_status` is `complete` or `unavailable_incomplete_coverage`. Category membership comes from applicable series in the observation panel. Every complete forecast total includes seven dates for every applicable category. Model predictions remain unrounded until display.

The application team should import only validated snapshots, pin map and chart reads to one run, use the existing area forecast for seller maps, and authorize individual-store reads against the active seller's store. Do not expose unrestricted `store_*`, candidate, model, or backtest downloads. Reuse the application's map/chart components when implementing the actual seller page; the Python widget is a development preview.

Run `python tests/test_notebook.py --execute` once dependencies are available. This runs the data tests, executes the actual training/export cells with 20-tree smoke settings, checks both saved models, renders Folium HTML, and exercises widget callbacks without retraining. A browser/Colab check is still needed for notebook rendering and map tiles.
