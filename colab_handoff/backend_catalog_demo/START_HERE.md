# Ready-to-run standalone Colab handoff

No sales were inserted into PostgreSQL. Existing store/catalog IDs came from
the local catalog snapshot; every generated sale and coverage record is synthetic.

## Do this now

1. Open Google Colab and choose File > Upload notebook.
2. Select Bale_Backend_Demo_Colab.ipynb from this folder.
3. Choose Runtime > Run all, using a CPU runtime.
4. When prompted by the notebook, select Bale_Backend_Demo_Inputs.zip.
5. Wait for training and save the results ZIP downloaded at the end.

No settings need editing. Keep this input ZIP separate from the training-results ZIP.
If the automatic download is blocked, download the printed ml_outputs/<run_id>.zip
from Colab's Files panel. Return with that results ZIP for the backend import step.

## Input profile

- 50,000 synthetic completed sale lines across 3 existing backend stores.
- 64 variants, 7 categories, 3 actual store barangays.
- 180 dates: 2026-05-13 through 2026-11-08.
- 2,880 simulated complete-reporting statements.
- Forecast dates: 2026-11-09 through 2026-11-15.
- One sellable_unit is one variant package/item, including multi-packs as one sale unit.
- Package contents are not converted. Category totals can mix package sizes.

backend_mappings.json stays local for later registration in the existing bale
database's forecast module. It creates no users, stores, products, orders or sales.
The original notebook is unchanged. No model has been trained by this preparation.
