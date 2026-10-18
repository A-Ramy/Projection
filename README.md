# Projection Tool — Total Cash Home Buyers

Quarterly **Projections**, **Production Trend Analysis (PTA)** and lead **Funnel** for the
company's live Google Sheet "Projection". The sheet is the source of truth and is read **read-only**
through a Google service account. Projections, overrides and settings live in the app's own
database, never in the sheet.

Live (private, invited team only): https://tchb-projection.streamlit.app/ — deployed from this branch; every push
redeploys it.

## What's in it

- **Projections**: a quarter starts pre-filled with the backbone (last quarter's actuals, or a longer window).
  1 Sources: type spend, revenue or deals per source and the rest is worked out; SELF GEN / Referral and the
  Follow Up group are projected by revenue or deals. 2 Deals by exit strategy. 3 Non-marketing costs. 4 Totals vs
  backbone and actual (vs pace while the quarter runs). Optional "Work Back From A Profit Target". Save at the start
  of the quarter; every version is kept.
- **PTA**: ACQ / FUS leaderboard with ▲▼ vs the previous period, trend per rep, KPI counts by type; period or
  cohort lead→deal.
- **Funnel**: lead lifecycle with leaks, cost vs profit per stage, all stages, conversion matrix; period or cohort;
  by source and by rep.
- **Data Quality**, **Settings** (start date, non-marketing lines, % base, thresholds, default window),
  **Backtest** (a finished quarter predicted from the months before it, with errors and MAPE).
- Total Cash Home Buyers brand (Baloo 2 + Nunito Sans, indigo / red / green, frosted glass) with a Light / Dark
  switch in the sidebar (it reloads the page once: save first).

Metric definitions: `docs/PLAN.md` §5 and `CLAUDE.md`. Build status: `docs/STATUS.md`.

## Run it locally

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                      # install dependencies
cp .env.example .env         # then fill in the values (see "Connect the sheet")
uv run streamlit run app.py  # opens http://localhost:8501
```

Without credentials the app shows the setup steps. To look at the UI with the small test fixture
instead of the live sheet: `PROJECTION_DEMO=1 uv run streamlit run app.py` (uses `tests/metrics_fixture.py`).

## Connect the sheet (service account, ~10 minutes)

1. In the [Google Cloud console](https://console.cloud.google.com) create a project and enable the
   **Google Sheets API** (APIs & Services → Library).
2. IAM & Admin → Service Accounts → **Create** (e.g. `projection-reader`). Grant no roles.
3. Open it → Keys → Add key → **Create new key → JSON**. Keep the file private.
4. In the Projection sheet click **Share** and add the service account's email as **Viewer**
   (untick "Notify"). With Viewer access plus the app's `spreadsheets.readonly` scope, the app
   cannot change the sheet.
5. Base64-encode the key: `base64 -w0 key.json` (Mac: `base64 -i key.json`) and put it in `.env`:

```
GOOGLE_SERVICE_ACCOUNT_JSON_B64=<the base64 text>
SHEET_ID=19RJ-hCH0rlOXJpHrnjDY_j_cDu_N4nA2uUuVxagQues
DATABASE_URL=            # optional locally: unset = SQLite file in .data/app.db
```

`.env`, `.streamlit/secrets.toml`, `.data/` and any data exports are gitignored. Never commit keys
or data.

## Data report

```bash
uv run python scripts/profile.py          # prints the report (aggregates only)
uv run python scripts/profile.py --save   # also writes .data/data-report.md (gitignored)
```

It lists, for data from the start date onward: months covered, COSTS names with the
marketing / non-marketing split, sources across the three tabs, distinct KPI / Quality / Stage
values, exit strategies, blank KPI dates, duplicate addresses, and every data issue found.

## Backtest from the command line

```bash
uv run python scripts/backtest.py                    # Q3 2026 predicted from Q1–Q2 (prints aggregates only)
uv run python scripts/backtest.py 2026-Q2 last_quarter
```

## Tests and lint

```bash
uv run pytest
uv run ruff check .
```

## Deploy (Streamlit Community Cloud + Neon)

1. Create a free Postgres database at [neon.tech](https://neon.tech) and copy its connection string.
2. At [share.streamlit.io](https://share.streamlit.io) sign in with GitHub → **New app** →
   repo `a-ramy/projection`, main file `app.py`.
3. **Advanced settings → Secrets**:
   ```toml
   GOOGLE_SERVICE_ACCOUNT_JSON_B64 = "..."
   SHEET_ID = "19RJ-hCH0rlOXJpHrnjDY_j_cDu_N4nA2uUuVxagQues"
   DATABASE_URL = "postgresql://..."
   ```
4. Deploy, then **Settings → Sharing**: make the app private and invite the team's emails.

Community Cloud installs from `requirements.txt`. Regenerate it after changing dependencies:
`uv export --no-dev --no-hashes --no-emit-project --format requirements-txt -o requirements.txt`.

## Layout

```
app.py                 entry point, navigation, brand injection
views/                 one file per page
ui/                    Streamlit helpers: brand.py + brand.css (tokens, glass, light/dark), html.py (sheet-style
                       tables, tiles, pills), layout.py (sidebar, tab capsule), state.py (cached loading)
projection/            engine, no Streamlit imports
  config.py            secrets and default settings
  periods.py           monthly grain and roll-ups (quarter, half, year)
  sheets.py            read-only Google Sheets access
  data/                parse → clean (start-date filter first) → validate → report
  metrics/             core parts and ratios, Follow Up, quarter view, pacing, funnel, PTA
  suggest/             lookback, D1 budgets (+ reverse), guardrails, D2 revenue, D3 plans, per-quarter accept
  model.py             the saved quarter projection
  planning.py          Projections-tab logic (start from history, unprojected spend, plans, reconciliation)
  backtest.py          backtest engine
  funnel_config.py     funnel stages, conversion pairs, previous-stage map
  storage.py           settings and per-quarter projection history
scripts/               profile.py (data report), backtest.py
tests/                 pytest suite; metrics_fixture.py has hand-worked answers
```
