# Messy hypothetical sales: use your existing notebook

Upload **Bale_Backend_Messy_Inputs.zip** when **Bale_Backend_Demo_Colab.ipynb** asks for its input ZIP.
Use a fresh Colab runtime (Disconnect and delete runtime, then reconnect) so an old
Bale_Backend_Demo_Inputs.zip is not selected automatically. Do not upload the results ZIP.
No notebook changes are needed. This folder contains no newly generated notebook.

## What you should see

- Exactly 50,000 sale lines, covering 2026-05-13 through 2026-11-08.
- 150 duplicate copies removed; 150 cancelled/voided lines excluded.
- 44 quarantined records: 12 invalid quantities, six missing product IDs, six
  unsupported statuses, and both records in each of 10 conflicting pairs.
- 49,656 accepted completed-sale lines. The expected global block is false.
- 400 original valid rows contain accepted formatting variations. Extra spaces,
  uppercase labels and BRGY. prefixes should normalize to the existing names.
- One corrupted combination: store/category ['1', '1']; its
  affected area/category is ['1102315009', '1']. These records have valid
  locations so they should withhold this combination, not stop the whole run.
- Store/category ['1', '2'] has partial reporting on
  2026-11-08; its current forecast should be withheld.
- Store/category ['1', '3'] reports two historical dates late:
  2026-08-16, 2026-08-30. Earlier forecast cutoffs must not see
  those sales or completeness statements prematurely. Eligible counts can vary.
- Other combinations still need to pass the unchanged notebook's eligibility rules.

Rows are shuffled. Sales patterns vary by store/category, including genuine zero
days, gradual changes and occasional bulk purchases. No model is forced to win.
Read the exported quarantine and cleaning files alongside the notebook explanation.
Accepted sale lines are not the same as forecastable groups or forecast rows.

## Why this is synthetic

Real backend catalog identities are reused, but all sale quantities and reporting
statements are invented. Package/item units are not converted into common weights
or volumes. Results test data cleaning and forecasting behavior; they do not prove
real business accuracy. Full scenario details are in dataset_manifest.json inside
the ZIP. Do not add or remove ZIP members without updating the notebook contract.
