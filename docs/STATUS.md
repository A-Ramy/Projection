# Status and working agreement

## How we work (owner's instruction)
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
| 4 | Finalize metric definitions from the real values | Claude → Owner | Owner approves | **Next** |
| 5 | Phase b: metrics engine + tests | Claude | All tests pass, incl. $37,500 and Follow Up roll-up | Not started |
| 6 | Phase c: Projections tab, saved quarters | Claude | Q1–Q3 totals reconcile to the sheet | Not started |
| 7 | First deploy: Neon + Streamlit Community Cloud (private, invited emails) | Owner with Claude | Team opens the URL; uninvited account blocked | Not started |
| 8 | Phase d: suggestions, overrides, guardrails, D3 profit target | Claude | Owner reviews Q4 suggestions | Not started |
| 9 | Phase e: PTA tab, then Funnel tab | Claude | Owner review | Not started |
| 10 | Phase f: glass styling, light/dark toggle, Title Case, charts, quarter history | Claude | Owner review against the mockup | Not started |
| 11 | First real run: Q4 2026 suggestions from Q1–Q3, Q4 actuals and pacing | Claude | Owner review | Not started |
| 12 | Backtest: Q3 predicted from Q1–Q2 vs Q3 actuals, error per source | Claude | Shown | Not started |
| 13 | Final README + CLAUDE.md | Claude | Done | Not started |

## Done so far
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
