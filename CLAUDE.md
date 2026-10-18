# CLAUDE.md — Projection Tool (Total Cash Home Buyers)

Streamlit app over the live Google Sheet "Projection" (ID `19RJ-hCH0rlOXJpHrnjDY_j_cDu_N4nA2uUuVxagQues`).
The approved plan, with full metric definitions, is the source of truth for scope; keep this file in
sync when a rule changes.

## Non-negotiables
- **Read-only sheet.** Only the `spreadsheets.readonly` scope; the service account is a Viewer. Never add
  write calls. App data (projections, overrides, settings) goes in the app database (`projection/storage.py`).
- **Privacy.** KPIs columns K (Full Name) and L (Phone) are never fetched in bulk. Column M (GHL Link) is
  hashed into `lead_key` in memory and discarded. Personal details appear only on an explicit drill-down
  (`sheets.fetch_contact_details`), never cached, logged or stored. Never commit data or secrets.
- **Never** print names/phones in reports, logs, tests or commit messages.

## Date rules
- One setting: `start_date` (default 2026-01-01). Nothing before it is used anywhere (no lookback either).
  Filter at load time, row by row (`projection/data/clean.py`).
- COSTS: Date ≥ start. Each row is a **month total**; bucket by calendar month (dates can be the 27th/30th).
- REVENUES: Date Closed ≥ start, grouped by month closed.
- KPIs: **Date** (trigger date) ≥ start. Blank Date = not triggered yet → excluded and counted.
- Except **All Leads**: every KPI = Lead row (any Quality, incl. Pending/blank Date) counts once by
  **Date Created** ≥ start. Net Leads (Qualified) count by Date, which on Lead rows is the Quality-change date.
- KPI and Stage names match funnel stages case-insensitively ("No-Show" = No-show).
- Monthly grain first, then roll up (`projection/periods.py` GRAINS: month, quarter, half, year).
- A month in progress has no costs. Cost comparisons run through the last cost-complete month and say so;
  revenue and KPIs run to today.

## Marketing vs non-marketing
- Non-marketing (setting `non_marketing`): ACQ Payroll, OPS Payroll, TC Payroll, DISPO Payroll, CONSULTING,
  General Expenses. Everything else in COSTS is a marketing source (incl. OctaTech, CALL (ReadyMode),
  SEO (NW WordPress)). New names default to marketing and are flagged.
- Non-marketing lines: manual projections only, no suggestions, not in the reverse-engineering logic.
- Sources join on the **exact** name across tabs. Near-duplicates are reported, never merged.

## Revenue rules
- Every REVENUES row is a deal (incl. $0 and negative rows). Revenue = sum.
- Blocks: main (Novation Deal, Wholesale, Retail Listing), Fix & Flip, Buy & Hold.
- **Follow Up** (per block): actuals = rows whose Source is not on the quarter's projection at all (no marketing
  line, no revenue row in any block). A projected source closing under an exit it has no row for gets an auto
  "(unprojected)" row under that source, never Follow Up (owner correction, 2026-10-18).
- P.% and A.% use one revenue base: total minus `pct_base_excluded_exits` (default Fix & Flip, Buy & Hold).

## Projecting a quarter (owner's model, 2026-10-18; `projection/plan.py`)
- Built at the start of the quarter on a **backbone**: the actuals of the quarter before (switchable: last 2
  quarters, all since start, custom). A new quarter is pre-filled as the backbone repeated, so it starts equal to it.
- Per source, type ONE of spend / revenue / deals; the rest follows from the backbone cost per deal and avg deal.
  Deals are placed on Source × Exit rows by the owner ("Place Deals By Backbone Mix" is optional help); deals not
  yet placed still count, at the source's avg deal. Avg deal is editable per exit row.
- The **active sources** (setting `active_sources`, owner's list) are projected on their own, no-cost ones (SELF GEN,
  Referral) by revenue or deals; every other source is projected as one **Follow Up** group (e.g. "3 deals").
- A source with spend but no backbone deals uses the longer window's cost per deal, only for numbers you type.
- Non-marketing lines start at the backbone cost and are typed. "Work Back From A Profit Target" is optional.

## Suggestions (key formulas)
- Suggested budget = target deals × leads per deal × CPL = target deals × cost per deal. Identical on an
  All Leads or Net Leads (Qualified) basis; show both chains and the implied leads.
- Test that must pass: $30,000 spend, CPL $150 (200 leads), 20 deals (LPD 10); 25 target deals → $37,500.
- Deals and revenue come from REVENUES (the KPI Closed Deal count is shown beside it, gaps flagged). Leads per
  deal and cost per deal use the source's deals across all exits. Default lookback: last completed quarter.
  Conversions default to same-period (cohort is the alternative view).
- Guardrails: insufficient data (0 leads or 0 deals), low confidence (< 30 leads or < 3 deals), scale flag
  (> 1.5× the source's best quarter since start).

## Conventions
- Engine (`projection/`: `data/` load+clean, `metrics/`, `suggest/`, `model.py` projection payload) has no Streamlit
  imports; Streamlit code lives in `app.py`, `views/`, `ui/`.
- Ratios are recomputed from summed parts, never averaged across months.
- Problems are surfaced as `Issue`s (Data Quality page), never skipped silently.
- UI: Total Cash Home Buyers brand (indigo #4D458A, red #BD2239, green #109648; Baloo 2 + Nunito Sans),
  frosted-glass style, Title Case UI text, light/dark toggle, no hover layout shifts. Tokens in `ui/brand.py`,
  rules in `ui/brand.css`, read-only sheet-style tables via `ui/html.py`; Streamlit's light/dark themes in
  `.streamlit/config.toml`. Escape `$` in markdown text (it starts math); HTML via `st.html` is safe.
- Every push to this branch redeploys https://tchb-projection.streamlit.app/: test before pushing.
- Run `uv run pytest` and `uv run ruff check .` before committing. Regenerate `requirements.txt` when
  dependencies change.
