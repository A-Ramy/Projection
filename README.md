# Projection Tool — Total Cash Home Buyers

Quarterly **Projections**, **Production Trend Analysis (PTA)** and lead **Funnel** for the
company's live Google Sheet "Projection". The sheet is the source of truth and is read **read-only**
through a Google service account. Projections, overrides and settings live in the app's own
database, never in the sheet.

Status: Phase a (data connection, 2026+ filtering, monthly grouping, validation). The Projections,
PTA and Funnel pages arrive in later phases.

## Run it locally

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                      # install dependencies
cp .env.example .env         # then fill in the values (see "Connect the sheet")
uv run streamlit run app.py  # opens http://localhost:8501
```

Without credentials the app shows the setup steps. To look at the UI with the small test fixture
instead of the live sheet: `PROJECTION_DEMO=1 uv run streamlit run app.py`.

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
app.py                 entry point and navigation
views/                 one file per page
ui/                    Streamlit helpers (cached loading, sidebar, issue list)
projection/            engine, no Streamlit imports
  config.py            secrets and default settings
  periods.py           monthly grain and roll-ups (quarter, half, year)
  sheets.py            read-only Google Sheets access
  data/                parse → clean (start-date filter first) → validate → report
  funnel_config.py     funnel stages and conversion pairs
  storage.py           settings and per-quarter projection history
scripts/profile.py     data report for the live sheet
tests/                 pytest suite with a hand-built fixture
```
