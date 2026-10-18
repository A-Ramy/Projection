# Status and working agreement

## How we work (owner's instruction)
- **Update 2026-10-18:** the owner asked to build everything remaining first (branding, suggestions, PTA, Funnel,
  Settings, Backtest) and then test it all together, instead of reviewing step by step. Steps 8–10, 12 and 13
  were built in one go; the owner's combined test (step 11 on the live app) is next.
- Walk the owner through **one step at a time**. Show only the current step; reveal the next one only
  after the current step is **verified done** (by a check Claude runs, or by the owner's confirmation
  where Claude can't check).
- Steps that need the owner (Google Cloud, environment settings, Neon, Streamlit Cloud): give exact clicks,
  never ask for keys or passwords in chat.

## Step tracker
| # | Step | Who | Gate (must pass before the next step) | State |
|---|---|---|---|---|
| 1 | Service account (project "TCHB Projection PTA", account systems@totalchb.com), Sheets API on, JSON key, sheet shared as Viewer, key saved as env var `GOOGLE_SERVICE_ACCOUNT_JSON_B64` | Owner | In a new session: variable present and valid JSON; read-only read of the sheet's tab names succeeds | **Done** (verified 2026-10-18) |
| 2 | Live data report (`scripts/profile.py`) | Claude | Runs; COSTS totals match the figures in the session handoff message | **Done** (verified 2026-10-18) |
| 3 | Owner reviews report (KPI/Quality/Stage values vs 15 funnel stages, duplicates, blank KPI dates, near-duplicate names, revenue sources with no leads, address match rate) | Owner | Owner confirms names and counting rules | **Done** (2026-10-18) |
| 4 | Finalize metric definitions from the real values | Claude → Owner | Owner approves | **Done** (2026-10-18) |
| 5 | Phase b: metrics engine + tests | Claude | All tests pass, incl. $37,500 and Follow Up roll-up | **Done** (2026-10-18) |
| 6 | Phase c: Projections tab, saved quarters | Claude | Q1–Q3 totals reconcile to the sheet | **Done** (2026-10-18) |
| 7 | First deploy: Neon + Streamlit Community Cloud (private, invited emails) | Owner with Claude | Team opens the URL; uninvited account blocked | **Done** (2026-10-18) |
| 8 | Phase d: suggestions, overrides, guardrails, D3 profit target | Claude | Owner reviews Q4 suggestions | **Built** · owner review in the combined test |
| 9 | Phase e: PTA tab, then Funnel tab | Claude | Owner review | **Built** · owner review in the combined test |
| 10 | Phase f: glass styling, light/dark toggle, Title Case, charts, quarter history | Claude | Owner review against the mockup | **Built** · owner review in the combined test |
| 11 | First real run: Q4 2026 suggestions from Q1–Q3, Q4 actuals and pacing | Owner with Claude | Owner review | **Next: combined owner test** |
| 12 | Backtest: Q3 predicted from Q1–Q2 vs Q3 actuals, error per source | Claude | Shown | **Built** (Backtest page + `scripts/backtest.py`) |
| 13 | Final README + CLAUDE.md | Claude | Done | **Done** (2026-10-18) |

## Done so far
- Steps 8–10, 12, 13 built (2026-10-18): brand layer (`ui/brand.py`, `ui/brand.css`, `ui/html.py`; light + dark
  Streamlit themes in `.streamlit/config.toml`, sidebar toggle writes Streamlit's per-page theme key and reloads),
  Projections in the mockup layout (C/A/B/D3, Start From Suggestions, unprojected-spend prompts, Use Plan A/B,
  month view), PTA, Funnel (period + cohort, previous-stage map, matrix), Data Quality cards, editable Settings,
  Backtest. Chart palette validated for colour-vision deficiency in both themes. Verified headless and in
  Chromium (light and dark) on live data.
- Step 8 built (2026-10-18): suggestions on the Projections tab (`projection/suggest/quarter.py`): window picker
  (only cost-complete months before the quarter), Suggested + Accept per line, Accept All (never replaces typed
  values), 🟠 Override when typing over an accepted value, drift note when the suggestion moves, implied
  leads/deals for any budget, guardrail notes, formula explanations, Profit Target panel with Plans A and B.
  Verified in Chromium on live data (Q4 learns from Jul–Sep 2026). Awaiting the owner's Q4 review.
- Step 7 (2026-10-18, owner): deployed at https://tchb-projection.streamlit.app/ from this branch (main file
  `app.py`, Python 3.12), secrets in Streamlit Cloud (key, SHEET_ID, Neon `DATABASE_URL`), app private with
  invited viewers; owner confirmed Q3 2026 loads and an uninvited account is blocked. **Every push to this
  branch redeploys the live app**, so run tests before pushing.
- Step 6 (2026-10-18): Projections tab (`views/projections.py`, logic in `projection/planning.py`): quarter picker
  (start → next quarter), editable Marketing / Non-Marketing cost lines and Revenue / Fix & Flip / Buy & Hold
  lines, Other marketing (unprojected), Follow Up drill-down, summary + pacing, month-by-month, Save / Discard /
  Copy previous quarter / Add lines for actuals, revision history. Live check: Q1–Q3 actual costs and revenue
  reconcile exactly to the sheet; editing, removing and saving verified in Chromium.
- Step 5 (2026-10-18): metrics engine `projection/metrics/` (core parts and ratios, Follow Up, quarter view with
  P.%/A.% and profit, pacing, funnel, PTA), suggestions `projection/suggest/` (lookback, D1 budget + reverse,
  guardrails, D2 revenue, D3 plans A/B), projection payload `projection/model.py`. Pending leads now kept
  (`Dataset.leads`, by Date Created) and KPI names matched case-insensitively. 75 tests pass, incl. $37,500 and
  the Follow Up roll-up; live Q3 PPC NW RDS numbers reproduce the Step 4 example.
- Step 2 verified (2026-10-18): `scripts/profile.py` ran on the live sheet; all handoff COSTS checks
  (quarter totals, source totals, blank cells, off-month-end date, 2026 separator rows) reproduced exactly.
  Report saved locally to `.data/data-report.md` (gitignored, never committed).
- Step 1 verified (2026-10-18): `GOOGLE_SERVICE_ACCOUNT_JSON_B64` decodes to valid service-account JSON;
  read-only (`spreadsheets.readonly`) read of the sheet's tab names returned COSTS, REVENUES, KPIs.
- Phases 0 + a code (commit `29d030e`): read-only fetch, parse/clean/validate, data report, Data Quality page,
  storage, 33 passing tests on a synthetic fixture.
- Approved plan: `docs/PLAN.md`. Approved mockup: https://claude.ai/artifact/8eiJupcBBgauLs9LnD2Rpf

## Step 3 decisions (owner, 2026-10-18)
1. KPI "No-Show" is the funnel's No-show stage (match stage names case-insensitively).
2. "Contract Rejected" is a KPI, not a Stage. Count KPI rows only; it shows 0 until some appear. The
   "6 Month Nurture - (Contract Rejected)" Stage is not counted as Contract Rejected.
3. Same thing, different spelling (owner will rename in the sheet; the tool still never merges):
   "SEO (CARROT)" = "SEO CARROT (TOTALCHB.COM)"; "PPC FL" = "PPC FL RDS"; the four near-duplicate
   rep spellings in the report's Lead Agent/AGENT rows are one person.
4. OctaTech and SEO (WBSFL) really have zero leads: show them with no CPL.
5. Sources with deals but no COSTS line are truly $0. SELF GEN is $0. Inbound Seller and the SMS sources were
   stopped; their closes are revived past leads and belong under Follow Up.
6. On Lead rows, Date = the date Quality changed; blank = still Pending. Pending leads count in **All Leads
   by Date Created** (≥ start). Net Leads (Qualified) keeps using the Quality date. Step 4 settles whether
   dated leads also use Date Created for All Leads.
7. Each REVENUES row is a deal, including repeat addresses (unchanged).
8. The 76% REVENUES→KPIs address match rate is normal.

## Step 4 decisions (owner, 2026-10-18) — written into docs/PLAN.md §5/§5b and CLAUDE.md
1. All Leads: every Lead row by **Date Created** (≥ start), any Quality incl. Pending. Net Leads: by Date
   (Quality-change date). Note for Step 5: `clean_kpis` currently drops blank-Date rows, so Lead rows must be
   kept with their Date Created.
2. Leads per deal and cost per deal use the source's deals across all exits.
3. Deal count comes from REVENUES; KPI Closed Deal is shown beside it and the gap flagged.
4. Default lookback: last completed quarter.
5. Guardrails as planned (< 30 leads or < 3 deals; 1.5× best quarter).
6. P.%/A.% base: all revenue except Fix & Flip and Buy & Hold (as planned).
7. Conversions default to same-period; cohort is the alternative view.
