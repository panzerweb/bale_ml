# Objective alignment and frontend integration

Decision record and integration guide, dated November 9, 2026.

This document records the agreed interpretation of the objective and functional requirement, the current manual notebook workflow, and the frontend/backend integration plan. It does not change the notebook, transaction schema, backend, or publication rules. **Existing** means implemented in the inspected backend checkout; **proposed** means design work that still needs implementation and verification. Existing code does not imply a deployed or completed end-to-end integration.

## 1. Objective and functional requirement

**Objective**

> Forecast product demand using machine learning models that analyze geographic sales trends, seasonal events, and user buying behavior, generating separate demand insights for each customer and each store.

**Functional requirement**

> The system shall accept business activity data and user location as inputs to produce and generate heatmaps based on product transactions.

### Agreed interpretation

| Term | Interpretation for the current scope | Boundary |
|---|---|---|
| Product demand | Estimate future recorded sale units using transaction history. Current notebook outputs are at category level. | Category demand is not an individual product/SKU forecast. Sales do not measure unmet demand; stockouts can suppress recorded purchases. |
| Geographic sales trends | Compare historical and forecast category sales across participating stores' barangays. | Notebook geography is the store's location, not the customer's residence. |
| User buying behavior | Aggregate purchasing patterns across time: quantities bought, category sales patterns, weekday differences, and recent sales changes. | Individual customer profiling and a separately trained model per customer are not required by this chosen interpretation. |
| Calendar patterns | Use the existing weekday, day-of-month, month, weekend, and historical sales features. | Calendar features do not establish that the model understands a specific holiday or festival. |
| Customer insights | Planned customer-facing views of permitted aggregate trends, contextualized by the customer's selected location. | This is a delivery approach, not a claim that individualized purchase predictions already exist. |
| Store insights | Own-store category forecasts, historical trends, and relevant transaction activity. | Forecasts require sufficient eligible history. A pooled model may produce different forecasts for each store; each store does not need its own trained model. |

### Seasonal-event decision

Keep the notebook and `transactions.csv` unchanged for now. Do not add `event_type`, `event_name`, or an event-calendar input in this phase.

Use this explanation in documentation and demonstrations:

> The model analyzes geographic sales trends and aggregate purchasing patterns over time. It uses weekday, day-of-month, month, and weekend features to capture calendar-related variation. Specific events, such as Christmas or local festivals, are not explicitly modeled in the current implementation.

The objective still says **seasonal events**, which is broader than the implemented calendar features. Record event-specific forecasting as a limitation/future enhancement. Do not claim full seasonal-event coverage. If formal objective revision is permitted, "calendar-related purchasing patterns" is closer to the implementation; this document does not itself revise the approved objective.

Likewise, delivering location-based aggregate insights to each customer is the proposed interpretation of customer delivery. If the formal assessment requires individualized buying predictions, that is additional work. Category-level outputs also need to be acceptable under the intended meaning of "product demand."

## 2. Chosen workflow: manual notebook handoff

```text
Application records POS sales and online orders
    -> Operator reviews identities, units, reporting coverage, and source overlap
    -> Operator exports a historical dataset
    -> Operator uploads inputs to Colab and runs the existing notebook
    -> Notebook evaluates methods and exports a versioned results ZIP
    -> Admin uploads the results ZIP to the backend
    -> Backend validates and stages the run
    -> Admin reviews and explicitly activates the run
    -> Frontend reads stored results through authenticated APIs
    -> Operator repeats after a later reporting period
```

1. POS transactions remain in `sales` / `sale_lines`; online purchases remain in `orders` / `order_items`. The training export reads eligible completed sales from these operational records. There is no requirement to copy every sale into a separate market-demand database.
2. The historical transaction heatmap has its own `transaction_heat_cells` aggregates. These support historical map queries and are separate from imported notebook forecasts.
3. Market-demand tables hold mappings, reporting evidence, imported observations, predictions, evaluation metadata, import jobs, and the active release selection.
4. Exported inputs include `transactions.csv`, `coverage.csv`, `areas.csv`, `categories.csv`, and an export manifest. Reviewed source mappings and reporting evidence are prerequisites. A day with no transactions is not automatically a complete zero-sales day.
5. Run the existing notebook with the intended data kind, cutoff, and input configuration. Use actual backend identities when forecasts must connect to application stores. Synthetic transactions remain synthetic even when they use real catalog IDs.
6. The notebook generates seven forecast dates. The backend imports saved results; opening a page or changing filters does not retrain a model.
7. Import and activation are separate. A failed import leaves the active run unchanged. An expired run retains its original forecast dates; the frontend must not relabel it as a new forecast.

There is no scheduled dataset submission, scheduled training, or automatic activation in this phase. The existing guide suggests manual weekly retraining review after reporting closes; frequency remains an operator decision based on completeness and measured results.

The notebook also supports `forecast_only` using trusted saved models and compatible updated history. That is distinct from `train`, which fits and evaluates again. Neither operation is a backend training endpoint in the current flow.

## 3. Separate the two map products

| Map | Source and geography | Current backend | Frontend meaning |
|---|---|---|---|
| Historical transaction heatmap | Operational transaction aggregates; online orders at delivery drop-off cells, POS sales at store cells. | `/analytics/heatmap` | Where recorded transaction activity occurred during a selected period. |
| Notebook forecast map | Imported category forecasts grouped by store barangay, positioned at supplied representative area coordinates. | `/analytics/market-demand/view` | Expected recorded category sale units at participating stores over the run's seven forecast dates. |

These maps have different geography, aggregation, eligibility rules, and update paths. Their totals are not automatically interchangeable. A delivery cell represents a transaction destination, not proof of customer residence. A barangay reference point is not a precise store or household location. Do not portray a barangay forecast as a street-level forecast.

**Current restriction:** real cross-store area maps, area history/totals, contributor counts, and pooled evaluation scores are withheld by the market-demand read service. Own-store forecasts can remain available. Synthetic area maps can be used in nonproduction demonstrations. Customer-facing or real cross-store forecast publication needs a backend publication policy and implementation; frontend work alone cannot enable it.

## 4. Existing backend endpoints

All paths in the following tables are relative to **`/api/v1`**.

### 4.1 Admin import and publication

| Method | Endpoint | Permission | Behavior |
|---|---|---|---|
| POST | `/admin/market-demand/imports` | `market_demand:import` | Multipart field `file` containing the results ZIP; returns HTTP 202 with an import ID. |
| GET | `/admin/market-demand/imports/{import_id}` | `market_demand:read` | Returns status, run ID when available, preview, and error. |
| GET | `/admin/market-demand/runs` | `market_demand:read` | Returns the current active ID and up to 50 recent runs. |
| POST | `/admin/market-demand/runs/{run_id}/activate` | `market_demand:activate` | Explicitly activates a staged run. |
| POST | `/admin/market-demand/runs/{run_id}/rollback` | `market_demand:activate` | Explicitly restores an older validated run. |

Import states are `queued`, `validating`, `importing`, `staged`, and `failed`. Poll the import-status endpoint until `staged` or `failed`. A queued import is not a published forecast.

Activation and rollback require:

```json
{
  "expected_active_run_id": null,
  "reason": "Reviewed initial forecast release"
}
```

Use `null` only when no run is active. Otherwise send the current active ID from the run list. On HTTP 409, refresh the list and require another deliberate review; do not silently retry with a changed expected ID. Use rollback for an older run.

HTTP import requires a configured Celery broker, a running worker, and shared private bundle storage between API and worker. The background job validates/imports; it does not train. Missing broker configuration returns 503; a stopped worker may leave the import queued. Uploaded Python/notebook/joblib contents are not executed by the importer. Synthetic import and activation are refused in production.

### 4.2 Store forecast reads

| Method | Endpoint | Behavior |
|---|---|---|
| GET | `/analytics/market-demand/options` | Active run, selected-store mapping, categories, areas, available methods, and scope availability. |
| GET | `/analytics/market-demand/view` | One pinned run selection containing forecast details, history, summaries, map points, coverage, and evaluation availability. |

Use the existing login and `POST /auth/store` flow to obtain a token for the selected store. The market-demand routes require current owner/manager authorization and an active store. Store identity comes from the token; do not add a `store_id` query parameter.

Example request, using IDs actually returned by `options`:

```http
GET /api/v1/analytics/market-demand/view?run_id=RUN_ID&scope=store&area_id=AREA_ID&category_id=CATEGORY_ID&model=recommended&map_view=forecast&lookback_days=90
```

| Query field | Contract |
|---|---|
| `run_id` | Required. Pin the run obtained from options. |
| `area_id`, `category_id` | Required. Choose supported IDs from options. |
| `scope` | `store` or `area`; explicitly use `store` for own-store details. The API default is `area`. |
| `model` | Default `recommended`; named choices are `lightgbm`, `xgboost`, `random_forest`, subject to availability. |
| `map_view` | `historical` or `forecast`. |
| `lookback_days` | 90 or 180 historical days for map totals. It does not change the seven-day forecast horizon. |

The response includes `run`, `selection`, `category`, `recommended_methods`, `displayed_methods`, `map`, and `detail`. Detail history is 28 daily points; forecasts contain seven daily points when available. The 90/180-day selector does not request a longer detail chart. The map remains area-scoped even when detail scope is `store`.

### 4.3 Historical analytics and saved locations

| Method | Endpoint | Purpose and access |
|---|---|---|
| GET | `/analytics/heatmap` | Historical transaction cells. Store management reads its own store; a base token with `analytics:read_all` reads platform analytics. It is not a general customer endpoint. |
| GET | `/analytics/best-sellers` | Historical product rankings by units or value, under the analytics scope guard. |
| GET | `/analytics/demand-forecast/{variant_id}` | Separate weekday-adjusted moving-average forecast. It is not the imported notebook result. |
| GET | `/me/addresses` | Current user's saved locations, available for a future customer location selector. |
| POST | `/me/addresses` | Save an address including required coordinates. Existing edit/default/delete routes can be reused. |

Historical heatmap filters:

- `metric`: `order_count`, `order_value`, `product_demand`, or `category_demand`.
- `from`, `to`: inclusive Manila calendar dates; default window is 30 days, maximum 366 days.
- `bounds`: viewport as `south,west,north,east`.
- `product_id`: only with `metric=product_demand`; `category_id`: only with `metric=category_demand`.
- `source`: `order` for online activity or `sale` for POS activity; omit for both.
- `store_id`: platform narrowing only, or the token's own store. Another store is refused for store-scoped access.

The response provides `cells` with `lat`, `lng`, `weight`, and `transactions`, plus the period, metric, `max_weight`, and suppression metadata. Cell centers are returned instead of original transaction coordinates. The suppression threshold is backend-controlled; it is not a frontend query setting.

## 5. Frontend interfaces

The following screens are the integration plan, not a claim that pages already exist in this checkout.

### 5.1 Admin: Forecast Management

| Section | Interface | Backend integration |
|---|---|---|
| Dataset preparation | Show the manual export/Colab instructions. If UI exports are later implemented, add dates, store selection, data kind, preparation status, coverage warnings, and download. | Current export/mapping CLI; optional proposed export APIs below. |
| Import results | ZIP picker, upload action, current import status, error details, and staged-run preview. Explain that the input dataset ZIP is different from the results ZIP. | POST imports, then GET import status. |
| Review and publish | Forecast cutoff/dates, real/demo label, available preview, active run, and activation reason. | GET runs, POST activate. |
| Run history | Run ID, generated time, forecast dates, freshness, active marker, and rollback reason/action. | GET runs, POST rollback. |

Do not add a button labeled "Train model" that claims to execute backend training. Use "Open training notebook" and explain the manual upload/Run all/download steps. The current CLI export writes files to a directory, not an HTTP download.

The current import preview and run summaries are limited to their existing response schemas. Do not assume a full admin run-detail or artifact-download endpoint exists. Detailed operator evaluation can be reviewed in the notebook and saved `run_report.md`. A richer in-app inspection view would need an additional backend contract.

### 5.2 Store: Demand Insights

Use two clearly labeled views:

**Historical Activity**

- Date range, metric, category/product filter, and online/POS filter.
- Transaction heatmap with units/legend and numeric cell totals.
- Best-selling products, if included in the page.
- Loading, no visible activity, and withheld-cell explanations. Suppressed data must not be presented as proven zero activity.

**Forecast**

- Default to the recommended method and own-store scope.
- Show category, seven forecast dates, expected recorded units, prior comparable week, and available percentage change.
- Plot the returned 28-day history and seven-day forecast, with a visible history/forecast boundary.
- Show data cutoff, generation time, forecast freshness, and coverage/availability messages.
- Show a forecast map only when the backend permits it. Keep own-store charts usable if area publication is withheld.
- Put available method comparisons in an optional advanced section. A named model change reads saved predictions and does not train.

Store read sequence:

1. Establish the selected store token.
2. Fetch `options`; handle `no_active_run` before requesting detail.
3. Select valid category/area and an available method. Respect `scope_availability`.
4. Fetch `view` with that `run_id` and selection.
5. Render only the latest matching response if filters change while requests are in flight.
6. Refresh options on a deliberate reload or store change. Do not mix components from different runs; an already open pinned view can remain consistent until refreshed.

### 5.3 Customer: Demand Near You — proposed

The chosen design uses **location-based aggregate purchasing patterns**, without changing the notebook or requiring individual purchase profiling.

- Choose a saved address, current location with permission, or a manually selected barangay.
- Show the selected area, category, historical/forecast choice, forecast period, and permitted aggregated insights.
- Label results as "Trends in your selected area" rather than "Your predicted purchases."
- Explain that selecting a location changes the area context; it does not change the geography underlying the trained sales forecast.
- Handle unavailable publication, unsupported location, no active run, and insufficient history explicitly.

Existing address APIs provide location storage, but do not connect location to forecast selection automatically. The backend must resolve the location to a reviewed supported area. It must not substitute the nearest representative barangay point for an authoritative area mapping without a defined rule.

This customer screen is blocked on a customer-authorized aggregate read service and publication policy. Do not grant customers admin/store analytics permissions or expose raw store records to bypass that gap. A location-adapted area view is not evidence of individualized forecasting; formal acceptance of that interpretation remains necessary.

## 6. Proposed endpoints and their priority

These routes do **not** exist yet. Names and payloads below are a proposed contract, not established implementation requirements.

### 6.1 Optional: UI-based dataset preparation

The manual workflow can operate today using the existing CLI, so these endpoints are optional for the first integration.

| Method | Proposed endpoint | Purpose |
|---|---|---|
| POST | `/admin/market-demand/exports` | Create an immutable dataset export job from a reviewed historical window. |
| GET | `/admin/market-demand/exports/{export_id}` | Return progress, reconciliation totals, coverage warnings, and failure details. |
| GET | `/admin/market-demand/exports/{export_id}/download` | Download the prepared input package after completion. |

Reuse the existing export service's validation: reviewed store/unit mappings, explicit real/synthetic provenance, overlap review, and a range ending before the current Manila day. Introduce an explicit export authorization; do not assume import permission covers raw dataset downloads. Mappings and reporting evidence can remain operator-managed through the current CLI in this phase.

### 6.2 Needed for the planned customer screen

| Method | Proposed endpoint | Purpose |
|---|---|---|
| GET | `/me/demand-insights/options` | Return approved categories, supported areas, active-run metadata, and view availability for customer use. |
| POST | `/me/demand-insights/view` | Resolve a location and return a pinned, permitted aggregate view. |

Proposed view inputs: `run_id`, `category_id`, historical/forecast selection, an allowed historical period, and exactly one location choice (`address_id`, coordinate pair, or supported `area_id`). Customer identity comes from authentication. Validate saved-address ownership and resolve coordinates on the backend. Location lookup does not need to create or update a saved address.

The response should identify resolved area, source geography, actual/forecast period, aggregation level, data cutoff, freshness, units, availability, and permitted map/chart values. Customer heatmaps must use a defined publication/aggregation policy. Reusing approved aggregate calculations is possible, but the existing store guard and real-area withholding must remain effective until a customer-specific service is implemented.

Historical transaction cells and notebook area forecasts need distinct source labels and selection rules in this service. Customer delivery does not require another training endpoint or a notebook change.

## 7. Display and release rules

- Read forecast values from backend JSON. Do not parse results ZIPs or load joblib files in the frontend.
- Display original run dates and `upcoming` / `current` / `expired` freshness. An old forecast is not a forecast for the next seven days from today.
- Keep missing historical observations as gaps; do not convert null values to zero. Hide percentage change when `comparison_reason` says it is unavailable.
- Handle `publication_withheld`, `insufficient_history`, `method_unavailable`, and other backend states without inventing values. Missing coordinates can leave valid analytical totals available in tables.
- Forecast uncertainty intervals are unavailable in the current notebook contract. Do not add confidence bands to its charts or borrow the separate moving-average endpoint's bands.
- Recommended methods may differ between area and store outputs. Store forecasts are independently modeled and need not sum to the area forecast. A baseline fallback is a valid disclosed result; do not label it as a tree-model forecast.
- Evaluation scores may be pooled across eligible groups, not individual-store accuracy. Preserve stage, scope, and training provenance. Forecast-only refreshes do not have newly measured future accuracy.
- Use the backend's forecast map scale consistently across method switches. Label recorded units; category/package units are not automatically interchangeable.
- Do not imply that demand forecasts are available stock, purchase recommendations, or population-wide consumption estimates.

## 8. Integration milestones and acceptance checks

### Milestone 1: existing admin/store contracts

- Operator prepares reviewed inputs through CLI and runs Colab manually; notebook remains unchanged.
- Admin imports a results ZIP, sees status/errors, reviews the run, and activates it deliberately.
- Failed imports and staged-but-unactivated runs do not replace the active run.
- Stale activation requests produce a visible conflict and reload path; rollback is explicit.
- Authorized owners/managers see their own returned forecasts; another store's data is inaccessible through query changes.
- Historical transaction heatmaps and imported forecasts are visually distinct.
- No-active-run, expired, missing-data, and publication-withheld states render correctly.
- Demo data is labeled synthetic; real cross-store forecast publication is not represented as available.

### Milestone 2: customer delivery

- Agree on and implement customer publication, aggregation, and location-to-area rules.
- Implement customer options/view endpoints using approved aggregate outputs.
- Saved locations belong to the authenticated user; unsupported areas have an explicit state.
- Customers receive context for their selected location without access to private store records.
- The interface accurately calls these aggregate area insights, and the objective's customer-delivery interpretation is accepted.

### Deferred

Scheduled exports/training/imports, automatic activation, explicit seasonal-event modeling, individual customer purchase predictions, and notebook changes are outside this decision. UI dataset exports and richer admin inspection are optional later improvements. Individual product ML forecasts would also require additional work if category-level output is not sufficient for the approved scope.

## 9. Source references

The sibling backend links assume `bale_ml` and `bale_backend_api` are checked out beside each other. Reference documents are design history; implemented contracts take precedence when describing current behavior.

- [ML workflow and limitations](ML_WORKFLOW_GUIDE.md)
- [Backend setup and manual runthrough](BACKEND_RUNTHROUGH.md)
- [Market-demand backend handoff](../bale_backend_api/app/modules/market_demand/README.md)
- [Admin routes](../bale_backend_api/app/modules/market_demand/admin_router.py)
- [Store forecast routes](../bale_backend_api/app/modules/market_demand/router.py)
- [Forecast query and response schemas](../bale_backend_api/app/modules/market_demand/schemas.py)
- [Forecast read/import/release behavior](../bale_backend_api/app/modules/market_demand/services.py)
- [Store authorization](../bale_backend_api/app/modules/market_demand/dependencies.py)
- [Export service](../bale_backend_api/app/modules/market_demand/exporter.py)
- [Operator CLI commands](../bale_backend_api/app/cli/commands/market_demand.py)
- [Historical analytics routes](../bale_backend_api/app/modules/analytics/router.py)
- [Historical heatmap filters](../bale_backend_api/app/modules/analytics/filters.py)
- [Analytics authorization](../bale_backend_api/app/modules/analytics/dependencies.py)
- [Customer saved-address routes](../bale_backend_api/app/modules/addresses/router.py)
