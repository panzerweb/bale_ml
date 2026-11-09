# BALE Market Demand: backend developer runthrough

Use this guide to set up another developer's device and run the complete local
workflow: generate CSV data, train in Google Colab, import the results ZIP, and
retrieve forecasts through the backend API. Commands below use Windows PowerShell.

This is the **standalone synthetic dataset workflow**. Training sales are generated
in files; they are not inserted into the application's sales or order tables.
The existing backend provides store/catalog identities and authentication.
Imported forecasts, observations, metadata, and evaluation results live in the
separate `market_demand` module's tables in the local `bale` database.

```text
Local backend catalog IDs -> generated CSV input ZIP -> Google Colab training
    -> results ZIP -> backend import -> explicit activation -> forecast read API
```

## 1. What you need and what Git does not transfer

- Git, Python 3.12 or newer, Docker Desktop with Compose v2, and a Google account
  for Colab. Backend repository instructions remain the source for its supported
  environment and dependency setup.
- Both repositories, including the matching Market Demand commits. A new backend
  alone does not provide the ML generator; a new ML checkout alone does not
  provide the backend endpoints or migration.
- A local development database containing active stores, owners, categories,
  products, and variants. Step 4 covers a new empty database.

Cloning code does **not** copy another developer's Docker volumes, databases,
Python environment, `.env`, accounts, uploaded archives, or active forecast run.
These ML paths are also ignored by Git:

| Path in `bale_ml` | How to obtain it on your device |
|---|---|
| `inputs/backend_catalog.json` | Export your backend's catalog in step 5 |
| `colab_handoff/` | Generate it in step 5 |
| `inputs/results/` and `ml_outputs/` | Download results from Colab or receive the reviewed results ZIP separately |

Do not substitute `Panabo_50k_Demo.zip` for an imported results ZIP. It is a
separate full-city **input** fixture with fictional identities. This guide uses
your backend's actual store/catalog IDs instead.

## 2. Clone both repositories and install the backend

Keep the repositories beside each other; several default paths assume this:

```text
Bale/
  bale_backend_api/
  bale_ml/
```

For a new workspace, run from your chosen projects directory:

```powershell
New-Item -ItemType Directory -Path Bale -Force
Set-Location Bale
git clone https://github.com/Etriii/bale_backend_api.git
git clone https://github.com/panzerweb/bale_ml.git
Set-Location bale_backend_api

python -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
```

If a repository already exists, update/check out the agreed integration branch
or commits there instead of cloning over it. Before continuing, confirm these
files exist:

- Backend: `app/modules/market_demand/` and
  `alembic/versions/f7a1c9e4d203_market_demand.py`.
- ML: `scripts/prepare_backend_colab.py` and
  `Panabo_Area_Demand_Forecastingg.ipynb`.

All backend commands below run from `bale_backend_api`. They call the interpreter
directly, so PowerShell environment activation is unnecessary. If you already
use `.venv`, replace `venv` with `.venv` throughout. On macOS/Linux, use
`venv/bin/python` instead of `venv\Scripts\python.exe`.

There is no local ML package installation required for this workflow. Dataset
preparation uses Python's standard library, and the Colab notebook installs its
own training dependencies. You can use the backend interpreter for preparation.

## 3. Configure the local environment and start Docker services

For a new backend checkout only, copy the tracked template:

```powershell
Copy-Item .env.exmple .env
```

The template is actually named `.env.exmple`. Preserve an existing `.env`; edit
its relevant values instead of overwriting it. Use these values for a **fresh
local Docker database with default credentials**, and keep the template's other
settings unless you need to change them:

```dotenv
ENVIRONMENT=development
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/bale
DATABASE_URL_ASYNC=postgresql+asyncpg://postgres:postgres@localhost:5432/bale
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=bale
POSTGRES_PORT=5432
REDIS_PORT=6379
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=
BACKUP_STORAGE_DIR=var/backups
RIDER_ROLE_NAME=rider
SECRET_KEY=REPLACE_WITH_YOUR_OWN_GENERATED_VALUE
```

Generate a local signing secret and paste its output into `SECRET_KEY`:

```powershell
.\venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Both database URLs must identify the same local database; only their drivers
differ. If an existing Docker volume uses different credentials or ports, use
those in the URLs and Compose settings. Editing `POSTGRES_PASSWORD` does not
change a password in an already initialized volume. Leave external mail/SMS/
payment credentials empty for this local forecast rehearsal.

Start Docker Desktop, then:

```powershell
docker compose up -d db redis
docker compose ps
```

Wait until both services are healthy. Docker Desktop should show the `bale`
project with PostgreSQL (`bale-db`) and Redis (`bale-redis`). The API and worker
will run on your computer in step 8, so they do not appear as new containers.

These instructions target the local `bale` database. An older optional demo
database is not required and can remain intact. Do not run database reset
commands or `docker compose down -v` to follow this guide.

## 4. Apply migrations and ensure a catalog exists

With `.env` verified to target your local database, inspect and apply migrations:

```powershell
.\venv\Scripts\python.exe -m alembic current
.\venv\Scripts\python.exe -m alembic upgrade head
.\venv\Scripts\python.exe -m alembic current
```

At the time of this handoff the head is `f7a1c9e4d203`, following
`e61c2b7a9d04`. A later checkout may have a newer head. An older database will
also receive pending existing backend migrations. Preserve a backup first if
the local data matters; this is an upgrade, not a database reset.

**If your database already has usable owners, stores, and catalog variants, skip
the seed commands below.** Use those identities in step 5.

For a new empty local development database, create the existing demo accounts
and only the catalog-related fixtures:

```powershell
.\venv\Scripts\python.exe -m app.cli seed-rbac
.\venv\Scripts\python.exe -m app.cli seed-all --only "store catalogs"
```

The selected seed subject includes its `catalog` and `stores` prerequisites.
It creates the application identities/catalog needed by this rehearsal without
selecting the order or POS-sale seed subjects. Do not run the full `seed-all`
or `market-demand-prepare-demo` command for this standalone training workflow.

On a newly seeded database, the published development accounts are
`demo_admin`, `demo_owner_one`, `demo_owner_two`, and `demo_owner_three`, with
password `password123`. Existing accounts keep their existing passwords; these
commands do not give you another developer's accounts or reset passwords.

## 5. Export identities and generate the standalone training inputs

From `bale_backend_api`:

```powershell
.\venv\Scripts\python.exe -m app.cli market-demand-export-catalog
.\venv\Scripts\python.exe ..\bale_ml\scripts\prepare_backend_colab.py
```

The first command reads your existing catalog into
`bale_ml/inputs/backend_catalog.json` and inserts no sales. Its default expected
database name is `bale`; if your intended local application database has another
name, pass `--expect-database YOUR_LOCAL_DATABASE_NAME` explicitly.

The second command generates 50,000 synthetic sale lines over 180 dates ending
yesterday in Manila, simulated reporting coverage, identity/unit mappings, and
a configured copy of the canonical notebook. It creates:

```text
bale_ml/colab_handoff/backend_catalog_demo/
  START_HERE.md
  Bale_Backend_Demo_Colab.ipynb
  Bale_Backend_Demo_Inputs.zip
  backend_mappings.json
  dataset_manifest.json
  transactions.csv, coverage.csv, and reference/summary CSVs
```

Check the generated summary and `START_HERE.md` for actual dates and group
counts. Only store/category combinations in your catalog participate. One
`sellable_unit` is one variant package/item; category totals may mix package
sizes. Generated quantities and coverage remain synthetic.

The generator refuses to overwrite an existing output directory. For another
run, choose a new directory, for example:

```powershell
.\venv\Scripts\python.exe ..\bale_ml\scripts\prepare_backend_colab.py --output ..\bale_ml\colab_handoff\backend_catalog_demo_run2
```

Use that same directory's notebook, input ZIP, and mappings together in all
remaining steps. To reproduce the original handoff's dates, use
`--end-date 2026-11-08` with a new output directory. That forecasts November
9-15, 2026; those dates are fixed and may be expired when you read this guide.

### If you already received the trained results ZIP

You can skip Colab training only after verifying that your local store,
category, product, variant, geography, and unit identities match the dataset
used for that ZIP. Store names alone do not establish matching IDs. Obtain
the accompanying `backend_mappings.json` and original input manifest/reference
files from the same handoff, review them against your local catalog, then
continue at step 7. A separately seeded database can allocate different IDs.

The original verified run was `20261109T032810Z-840a7e1a`, forecasting November
9-15, 2026. Its ZIP is **not included by a normal clone**. Receive it separately
with its matching mappings or generate/train a new handoff on your device.
Do not edit an exported ZIP's IDs, dates, or checksums to force compatibility.

## 6. Train in Google Colab and download the results ZIP

1. Open [Google Colab](https://colab.research.google.com/).
2. Choose **File > Upload notebook** and select the generated
   `Bale_Backend_Demo_Colab.ipynb`, not the unconfigured root notebook.
3. Use a CPU runtime and choose **Runtime > Run all**.
4. When prompted, upload `Bale_Backend_Demo_Inputs.zip` from the same directory.
5. Let all cells complete training, evaluation, and export. Keep the configured
   `MODE="train"`, synthetic provenance, and generated dates.
6. Save the results ZIP automatically downloaded at the end. If download is
   blocked, find the printed `ml_outputs/<run_id>.zip` in Colab's Files panel
   and download it manually.

No database connection or backend credentials are needed in Colab. The notebook
trains LightGBM, XGBoost, and Random Forest and evaluates area/store forecasts
separately. It exports the chosen methods and available candidate results.
The backend subsequently serves saved results; API requests do not train models.

Keep the two archives distinct:

| File | Destination |
|---|---|
| `Bale_Backend_Demo_Inputs.zip` | Upload to the generated Colab notebook |
| `<run_id>.zip` from `ml_outputs/` | Upload to the backend import endpoint |

Optionally retain your downloaded results under `bale_ml/inputs/results/`;
that directory is ignored by Git. Keep the downloaded archive unchanged.

## 7. Register the matching backend mappings

From `bale_backend_api`, before importing results:

```powershell
.\venv\Scripts\python.exe -m app.cli market-demand-map --file ..\bale_ml\colab_handoff\backend_catalog_demo\backend_mappings.json
```

Replace the path if you used another handoff directory. This registers reviewed
areas, store-to-area mappings, and variant units. It creates no business sales,
orders, users, stores, or products. It must reference identities that already
exist in your database. Identical mappings can be reapplied; conflicting
mappings are refused rather than silently overwritten.

## 8. Start the API and import worker

Open **two PowerShell terminals**, both in `bale_backend_api`, using the same
`.env` and working directory.

Terminal 1, API:

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2, Celery worker:

```powershell
.\venv\Scripts\python.exe -m celery -A app.jobs.worker worker --pool=solo -l info
```

The `solo` pool supports a Windows host. The worker consumes
`market_demand.import`; a beat scheduler is not required for this manually
triggered import. Avoid starting a second worker setup through the Compose
`jobs` profile or `app.cli start` at the same time.

API and worker must use the same database, broker, and private archive storage.
Running both on the host from this directory makes `var/backups` shared by
both. The current Compose worker setup does not provide a host/container shared
archive volume for this flow; use the host worker above. If containerizing
both later, mount the same archive volume into both processes and configure
their database/Redis hosts for the Docker network.

Open [Swagger UI](http://127.0.0.1:8000/api/docs). The schema is at
`http://127.0.0.1:8000/api/openapi.json`. Seeing database and Redis containers
alone in Docker Desktop is expected with this setup.

## 9. Import, inspect, and activate in Swagger as an admin

### A. Authenticate

Click **Authorize** and use the OAuth2 username/password section with your
admin credentials. For a new demo seed, use `demo_admin` / `password123`.
Alternatively, `POST /api/v1/auth/login` accepts form fields `username` and
`password`; paste the returned `access_token` into Swagger's HTTPBearer
authorization field. That field takes the token without the `Bearer ` prefix.

Admin operations require `market_demand:read`, `market_demand:import`, and
`market_demand:activate`, seeded for `admin` and `super_admin` by the migration.

### B. Upload the results archive

Under **Admin · Market Demand**, execute:

```text
POST /api/v1/admin/market-demand/imports
```

Use **Try it out**, select the downloaded **results** ZIP in multipart field
`file`, and execute. Expect **202 Accepted** and an `import_id`. This means
the work was queued, not that the forecast is ready or active.

### C. Wait for a staged import

```text
GET /api/v1/admin/market-demand/imports/{import_id}
```

Repeat with the returned import ID until `status` is `staged` or `failed`.
Successful processing normally moves through `queued`, `validating`,
`importing`, and `staged`; fast imports may finish before you observe each
intermediate status. Inspect `preview`, `run_id`, or `error` in the response.
Do not activate a failed or still-processing import.

### D. Read the current active run

```text
GET /api/v1/admin/market-demand/runs
```

Note the top-level `active_run_id`. Also confirm the staged run's forecast
dates, data kind, and recommended methods before activation.

### E. Activate the staged run

```text
POST /api/v1/admin/market-demand/runs/{run_id}/activate
```

The path's `run_id` is the **new run to activate**, copied from the import
response. The body identifies the **currently active run** and an audit reason.
For the first activation, when the list endpoint returned `active_run_id: null`:

```json
{
  "expected_active_run_id": null,
  "reason": "Reviewed synthetic Colab results for local integration testing"
}
```

Use actual JSON `null`, without quotes. Replace Swagger's `"string"` placeholder.
If a run is already active, set `expected_active_run_id` to that exact current
ID instead. For example, when replacing the original verified run:

```json
{
  "expected_active_run_id": "20261109T032810Z-840a7e1a",
  "reason": "Activate the newly reviewed synthetic training run"
}
```

Expect **200 OK** and `active: true`. Refresh the run list to confirm.
Import alone never activates. The conflict message **"The active run changed.
Refresh run history before activating."** means the body did not match the
current active ID. Read `/runs` again and use its latest `active_run_id`.

To deliberately restore an older validated run, use the separate
`POST /api/v1/admin/market-demand/runs/{run_id}/rollback` endpoint with the same
expected-current check and a reason explaining the rollback.

## 10. Retrieve the logged-in store's forecasts

Admin upload credentials and a store owner's selected-store token have
different purposes. To exercise owner reads:

1. In Swagger, log out existing authorizations so an old admin/base token does
   not override the token you paste next.
2. Execute `POST /api/v1/auth/login` using the owner's form credentials. For
   a newly seeded database, `demo_owner_one` / `password123` is an example.
3. Authorize with this owner's returned base `access_token` through HTTPBearer.
4. Execute `POST /api/v1/auth/store` with an owned store's actual local ID:

   ```json
   {"store_id": 1}
   ```

   `1` is an example from the original database, not a portable guarantee. Find
   your store ID using existing store APIs and the exported catalog snapshot.
5. Replace the HTTPBearer value with the **new access token returned by the
   store-selection endpoint**. Clear any OAuth2 authorization still holding a
   different token.
6. Execute `GET /api/v1/analytics/market-demand/options`.

After activation, options should report `state: "ready"`, the run, active store,
available categories/areas/methods, and scope availability. With no active run,
it returns `state: "no_active_run"`. For a store forecast, choose the
`active_store.area_id` and an available category represented in that store's
catalog. Populate Swagger's `/view` query fields:

| Field | Value |
|---|---|
| `run_id` | `run.run_id` from options |
| `scope` | `store` for this store, or `area` for barangay detail |
| `area_id` | The store's reviewed area for `store` scope |
| `category_id` | A category ID from options, present in the chosen scope |
| `model` | `recommended`, `lightgbm`, `xgboost`, or `random_forest`, when available |
| `map_view` | `forecast` or `historical` |
| `lookback_days` | `90` or `180`; this changes historical map lookback |

For the original matching database/run, this is a concrete example:

```text
GET /api/v1/analytics/market-demand/view?run_id=20261109T032810Z-840a7e1a&scope=store&area_id=1102315009&category_id=1&model=recommended&map_view=forecast&lookback_days=90
```

The forecast horizon remains **seven days**. There is no `store_id` query
parameter; the backend takes it from the store token and rechecks access.
Switching stores requires selecting that store and using its returned token.

Check the response:

- `detail.forecast`: seven dated predictions when that group/model is available.
- `detail.history`: 28 recent historical dates, preserving unknown values.
- `detail.summary`: forecast total and comparable-week information.
- `detail.coverage` and `detail.performance`: reporting and evaluation information.
- `map.points`: barangay totals and coordinate/availability information.
- `run` and `displayed_methods`: forecast dates, data kind, and resolved models.

Switch through the available models and verify dates stay the same while
forecast values and the selected performance results update together. Historical
values stay unchanged. Missing data/methods must display as unavailable, not
zero. Area and store models are independent; do not sum store forecasts to
manufacture an area forecast. Real cross-store map publication is currently
withheld; the synthetic rehearsal permits the area demonstration.

These responses support the proposed owner selectors, map, chart, summary cards,
coverage indicator, and performance panel. Admin endpoints support upload,
import status, run history, activation, and rollback controls. Frontend wiring
is separate work; this handoff does not claim an implemented frontend screen.

## 11. Troubleshooting

| Symptom | What to check |
|---|---|
| Missing command or route / 404 | Both checkouts contain the matching integration commits; restart API and worker after updating. Swagger is `/api/docs`, not `/docs`. |
| Database connection fails | Docker services are healthy; both database URLs, existing volume credentials, and exposed ports match. Check for stale `DATABASE_URL` shell overrides pointing to another database. |
| `No active stores with active catalog variants` | An empty database needs the identity/catalog bootstrap in step 4, or existing active stores and catalog records. No sales history is required for this file-only generator. |
| Missing catalog or handoff files | They are ignored by Git. Export/generate them locally; a clone does not contain another device's generated handoff. |
| Output directory already exists | Choose a fresh `--output` path and consistently use that handoff's files. |
| Unreviewed store location | The generator currently uses the Panabo reference registry in `data/panabo_reference.json`. Review/correct location data or extend the registry deliberately; do not invent a mapping to force a match. |
| Upload returns 503 | Configure `CELERY_BROKER_URL`, ensure Redis is reachable, and restart API and worker with the same environment. |
| Import stays queued | The worker must be running against the same broker as the API and current code. Inspect its terminal for errors. |
| Worker cannot read the uploaded archive | API and worker need the same `BACKUP_STORAGE_DIR` and shared filesystem; use the two host terminals in step 8. |
| Import fails validation | Read the import's `error`; confirm it is a results ZIP, mappings exist, and dataset/catalog IDs and units match. Keep the original files/checksums intact. |
| Activation returns 409 conflict | Refresh `/runs`; put its current `active_run_id` in the body, including unquoted `null` when none is active. |
| 401 or missing store context | Log in again if expired; use the store-selection token, not the base/admin token. Clear stale Swagger authorizations. |
| 403 on store forecast | Verify current owner/manager access, active store, and that the requested area matches the store mapping. Cashier/stock roles cannot read these forecasts. |
| Empty/unavailable forecast | Inspect group/model availability and category/scope; activation cannot manufacture a forecast omitted during training. |
| Run marked expired | Dates come from training and are not relabeled on import. Generate/train a new dated run when you need a current forecast. |
| `psycopg` reports no usable libpq | Install the matching binary extra in the backend environment: `python -m pip install "psycopg[binary]==3.3.3"` for the current requirements, or supply the appropriate PostgreSQL client library. |

Uploads are limited to 100 MiB compressed and 512 MiB expanded by default.
Original ZIPs stay in private archive storage under `market-demand/`; the API
does not deserialize or execute uploaded `.joblib`/Python models. Model weights
are not loaded into the serving database for inference.

## 12. Checks before handing over commits and future runs

Make sure the commits include the generator and its tests in `bale_ml`, and the
module, migration, registrations, and tests in `bale_backend_api`. The backend
developer must receive both matching sets of changes. Do not commit `.env`,
private keys, virtual environments, local database backups, or generated
catalog/results files just to make a clone work.

Useful focused checks, run from `bale_backend_api`:

```powershell
.\venv\Scripts\python.exe ..\bale_ml\tests\test_backend_colab.py
.\venv\Scripts\python.exe -m pytest test/market_demand test/auth test/store_users/test_store_token.py test/seller_insights test/router_audit test/background_jobs/test_schedules.py test/migrations/test_permission_seeds.py -q
```

PostgreSQL-specific tests are opt-in and require a separate disposable database;
do not point their test URL at your application database. See the module's
`README.md` and `test/market_demand/test_postgres.py` for its guard and setup.
The backend module's `VERIFICATION.md` records earlier verification evidence
and pre-existing wider-suite failures; this guide does not claim the entire
backend suite passes or that another device has been tested already.

For each subsequent synthetic demonstration: export current identities if they
changed, generate a new handoff directory, train in Colab, register any new
reviewed mappings, upload, inspect, and activate with the current active ID.
Mapping changes that conflict with already registered identities need an
explicitly reviewed change rather than an overwrite. A new run's dated results
remain pinned by `run_id`; refresh options to discover a newly active run.

For normal daily API use after a successful import, start Docker PostgreSQL/
Redis and the API, log in/select a store, then call `options` and `view`.
Reading forecasts does not require Colab or an import worker. Keep the worker
running when importing another ZIP; other backend features may require their
own worker/scheduler services as described in the backend README.

Stop the host API/worker with Ctrl+C when finished. `docker compose stop db redis`
stops these local services while retaining the database volume.

Further references:

- [ML input, evaluation, and export details](ML_WORKFLOW_GUIDE.md)
- Backend: `app/modules/market_demand/README.md`,
  `app/modules/market_demand/VERIFICATION.md`, and the repository `README.md`
- Canonical training notebook: `Panabo_Area_Demand_Forecastingg.ipynb`
