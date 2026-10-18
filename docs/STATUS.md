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
| 1 | Service account (project "TCHB Projection PTA", account systems@totalchb.com), Sheets API on, JSON key, sheet shared as Viewer, key saved as env var `GOOGLE_SERVICE_ACCOUNT_JSON_B64` | Owner | In a new session: variable present and valid JSON; read-only read of the sheet's tab names succeeds | **1a–1g done by owner, verification pending** |
| 2 | Live data report (`scripts/profile.py`) | Claude | Runs; COSTS totals match the figures in the session handoff message | Not started |
| 3 | Owner reviews report (KPI/Quality/Stage values vs 15 funnel stages, duplicates, blank KPI dates, near-duplicate names, revenue sources with no leads, address match rate) | Owner | Owner confirms names and counting rules | Not started |
| 4 | Finalize metric definitions from the real values | Claude → Owner | Owner approves | Not started |
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
- Phases 0 + a code (commit `29d030e`): read-only fetch, parse/clean/validate, data report, Data Quality page,
  storage, 33 passing tests on a synthetic fixture.
- Approved plan: `docs/PLAN.md`. Approved mockup: https://claude.ai/artifact/8eiJupcBBgauLs9LnD2Rpf
