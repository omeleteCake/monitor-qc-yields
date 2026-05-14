# Québec Political Risk & Yield Spread Dashboard

A Streamlit dashboard for monitoring Québec political separation risk, Québec provincial yield spreads, liquidity/event signals, ratings, and fiscal notes.

The dashboard is deliberately built **without Bloomberg, CanDeal, LSEG, or any proprietary provincial bond feed**. Government of Canada benchmark yields are fetched automatically from the official Bank of Canada Valet API. Québec and Ontario provincial yields are entered manually, imported from CSV, or persisted locally to a CSV controlled by the user.

## Features

- Automatic Bank of Canada selected benchmark yield ingestion for GoC 2Y, 3Y, 5Y, 7Y, 10Y, and Long/30Y where available.
- Manual editable table for Québec and Ontario provincial yield marks.
- CSV import/export for the provincial data layer.
- Local CSV persistence at `data/provincial_yields_local.csv` for manually entered marks.
- Clearly labeled synthetic sample CSV for demos only.
- Summary metric cards for GoC 10Y, Québec-Ontario 10Y/30Y spreads, Québec-GoC 10Y/30Y spreads, rating-watch flags, and auction concession.
- Political monitor with links to 338Canada Québec projection and sovereignty-polling pages plus manual political fields.
- Plotly charts for GoC yields, Québec-Ontario spreads, Québec-GoC spreads, and optional liquidity fields.
- Alerts for spread widening, rating-watch flags, bid-ask thresholds, and referendum commitment flags.
- Ratings/fiscal monitor with an official Québec credit-ratings link, best-effort table display, manual fallback table, and fiscal notes.
- Optional public dealer snapshot adapters for RBC Direct Investing and Edward Jones pages, treated only as unstable, partial, non-authoritative spot checks.

## Repository structure

```text
repo/
  app.py
  data/
    market_data_template.csv
    sample_market_data.csv
  utils/
    boc.py
    loaders.py
    calculations.py
    sources.py
  tests/
    test_calculations.py
  requirements.txt
  README.md
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Python 3.11 or later is recommended.

## Run the dashboard

```bash
streamlit run app.py
```

The app can be useful with only Bank of Canada data plus manual provincial entries. If no provincial rows have been saved, the manual-entry table starts with one blank row for the current date.

## Run tests

```bash
pytest
```

## Provincial market data model

### Required columns

```csv
date,qc_5y,qc_10y,qc_30y,on_5y,on_10y,on_30y
```

### Optional columns

```csv
qc_2y,on_2y,bidask_qc_10y_bp,bidask_qc_30y_bp,auction_concession_bp,rating_watch_flag,event_note
```

### Column notes

- `date`: Any date format parseable by pandas/dateutil. The app sorts observations by date.
- `qc_*` and `on_*`: Québec and Ontario yields in percent, not decimals. Example: use `3.75` for 3.75%.
- `qc_2y`, `on_2y`: Optional because core spread monitoring uses 5Y, 10Y, and 30Y.
- `bidask_qc_10y_bp`, `bidask_qc_30y_bp`: Optional bid-ask width in basis points.
- `auction_concession_bp`: Optional auction concession in basis points.
- `rating_watch_flag`: Optional boolean-like field; accepted true values include `true`, `yes`, `1`, `watch`, and `negative`.
- `event_note`: Optional free-text note shown in the event monitor.

A CSV template is available at `data/market_data_template.csv`. A synthetic demonstration file is available at `data/sample_market_data.csv`; it is not market data and should not be used for production decisions.

## Manual workflow for provincial yields

1. Open the app with `streamlit run app.py`.
2. Enter Québec and Ontario 5Y/10Y/30Y marks in the editable table.
3. Optionally enter 2Y marks, bid-ask width, auction concession, rating-watch status, and event notes.
4. Click **Save manual table locally** to persist rows to `data/provincial_yields_local.csv`.
5. Use **Export current table** to download the current table for backup or review.
6. Use the sidebar CSV uploader to import rows from an external file. Uploaded rows override local rows for matching dates in the in-memory layer.

`data/provincial_yields_local.csv` is ignored by git so local marks are not accidentally committed.

## Public vs manual/private data layers

### Official public automated layer

- **Government of Canada benchmark yields** are fetched automatically from the Bank of Canada Valet CSV endpoint:
  `https://www.bankofcanada.ca/valet/observations/group/bond_yields_benchmark/csv`
- **Bank of Canada selected bond yields reference** is linked in the dashboard:
  `https://www.bankofcanada.ca/rates/interest-rates/canadian-bonds/`

### Manual provincial layer

- Québec and Ontario provincial secondary-market yields are manual/user-supplied through the editable table, CSV upload, or local CSV persistence.
- The app does **not** invent missing provincial time series and does **not** assume a clean public API exists for Québec/Ontario secondary-market yields.
- Production users can populate the CSV manually from approved public snapshots, internal marks, dealer runs, or another governed process.

### Optional public dealer spot checks

The app links to and can attempt lightweight table/metadata extraction from:

- RBC Direct Investing bond rates: `https://www.rbcdirectinvesting.com/pricing/gic-bond-rates.html`
- Edward Jones provincial bonds: `https://www.edwardjones.ca/ca-en/investment-services/investment-products/fixed-income-investments/provincial-bonds`

These pages are treated as **indicative, partial, unstable, and non-authoritative**. They are not benchmark history and are not automatically used in spread calculations. If a page fails or changes layout, the dashboard continues to work with Bank of Canada data and manual provincial input.

### Political and ratings references

- 338Canada Québec projection page and sovereignty-polling page are linked as external references.
- The app does not scrape rendered 338Canada charts.
- Québec credit ratings are linked to the official Government of Québec ratings page. The app attempts a best-effort table display and falls back to manual ratings entry when parsing fails.

## Calculations

The core spread calculations are in basis points:

- `qc_on_5y_spread_bp = (qc_5y - on_5y) * 100`
- `qc_on_10y_spread_bp = (qc_10y - on_10y) * 100`
- `qc_on_30y_spread_bp = (qc_30y - on_30y) * 100`
- `qc_goc_5y_spread_bp = (qc_5y - goc_5y) * 100`
- `qc_goc_10y_spread_bp = (qc_10y - goc_10y) * 100`
- `qc_goc_30y_spread_bp = (qc_30y - goc_30y) * 100`

The Bank of Canada `Long` benchmark is mapped to `goc_30y` for dashboard display.

## Alert definitions

Alerts are displayed in severity order: **critical**, **warning**, then **info**.

- **10Y spread widening**: Warning if `qc_on_10y_spread_bp` widens by more than 5 bps over 5 observations.
- **30Y spread widening**: Critical if `qc_on_30y_spread_bp` widens by more than 7 bps over 5 observations.
- **Rating watch flag**: Critical if the latest manual/CSV row has `rating_watch_flag` set to a truthy value.
- **Referendum commitment**: Critical if the user marks `referendum_commitment_flag` in the political monitor.
- **30Y liquidity threshold**: Warning if `bidask_qc_30y_bp` exceeds the user-set sidebar threshold.
- **No active alerts**: Informational message when no rules are breached.
- **No market data**: Informational message when no valid manual/CSV/sample provincial rows are available.

## Operational notes

- Bank of Canada data is cached for one hour with Streamlit caching.
- The sidebar refresh button clears cached public-source data.
- Source-page failures are handled gracefully and should not crash the app.
- Chart rendering skips missing optional fields.
- This dashboard is a monitoring tool, not a trading system or legal/political forecast.

## Future extension ideas

- Bloomberg export integration, if a licensed export becomes available.
- CanDeal export integration, if a licensed export becomes available.
- Database backend for audited manual marks and user attribution.
- Scheduled refresh with persisted Bank of Canada snapshots.
- Email or messaging-system alerts.
- Authentication and role-based fiscal/risk commentary workflows.
- Formal market-data quality checks and outlier review queues.
