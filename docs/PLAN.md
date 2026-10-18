# Plan: Quarterly Projections + Production Trend Analysis (PTA) tool

## Context
Approved clickable mockup: https://claude.ai/artifact/8eiJupcBBgauLs9LnD2Rpf

Projections and PVA are tracked by hand in a Google Sheet today. The app will read the live "Projection" sheet **read-only**. It replaces the manual projection layout, fills in actuals automatically, and suggests marketing budgets and revenue targets from 2026+ history. It also adds a per-rep production trend view (PTA). The repo `a-ramy/projection` is empty, so everything is new. Work goes on branch `claude/real-estate-projections-tool-5cqusz`.

---

## 1. What I could inspect so far (and what is still blocked)

**How I got the data.** The Drive connector returned only the first ~35 rows of each tab, all from 2024. A CSV export through Drive gave me the **entire COSTS tab**, because it is the first tab. REVENUES and KPIs can only be read in full through the Sheets API with the service account (step 0). Their profiling report is therefore the first deliverable of Phase a. I won't guess their numbers.

### COSTS, 2026+
Profiled from the live sheet on 2026-10-17 (figures are not stored in git; rerun `scripts/profile.py`).
Non-marketing: the 4 payroll lines, CONSULTING, General Expenses. Everything else is marketing.

Confirmed: OctaTech, CALL (ReadyMode) and SEO (NW WordPress) are all **marketing**. The classification is stored as an editable setting (a list of non-marketing names), so any line can be moved later without code changes.

### Mismatches with the brief found so far
1. **Curative Title** is in your projected marketing list but has **no COSTS rows in 2026**. Confirmed as a **no-cost source**: it stays projectable with $… actual cost, and its leads and deals still count.
2. **PPC FL RDS** has $… of spend in Q3 but isn't in your projected list. It will appear on "Other marketing (unprojected)" until you add it.
3. Month-end dates are not always month end. June 2026 is dated **6/27/2026**, and 2024 used the 30th. Costs are therefore bucketed by calendar month, never by exact date.
4. Three cost cells are **blank**: Feb SEO (CARROT), Feb CALL (ReadyMode), Mar SEO (CARROT). They are treated as $… and listed in validation.
5. There are 9 blank separator rows in 2026. They are skipped and counted.
6. Several sources have very little history (Lead Zolo 1 month, SEO (WBSFL) 1 month, Facebook stopped after July). Expect "low confidence / insufficient data" on these, as you anticipated.
7. From the 2024 sample: **KPIs is sorted by Date Created, not Date**, so every load scans the whole tab. Also, **REVENUES addresses are street-only** ("3060 SE Fairmont St") while KPIs addresses include city, state and zip. The cohort view therefore needs address normalization, and I'll report the match rate.
8. **P.% / A.% inconsistency.** Your sheet's P.% divides by revenue excluding F&F, while A.% divides by revenue including F&F. Fixed: both now use the same base, **revenue excluding Fix & Flip and Buy & Hold** (Novation + Wholesale + Retail Listing). This is one setting, stored as a list of excluded exit strategies.

### Decisions you've made (locked in)
- Revenue % base: **excl. Fix & Flip and Buy & Hold**, applied to both P.% and A.%.
- Leads: show **All Leads** (Qualified + Disqualified) and **Net Leads** (Qualified only), with CPL and Net CPL. Your "show both budgets" choice turns out to be moot: target × (leads ÷ deals) × (cost ÷ leads) = target × cost per deal, so both bases always give the **same budget**. The tool therefore shows **one suggested budget**. Its explanation shows both calculations, plus the implied All and Net leads for that budget.
- **Buy & Hold**: its own block below Fix & Flip, with the same source and Follow Up rules.
- **Every REVENUES row is a deal**, including $… and negative rows (no de-duplication). Phase a still lists the 2026 duplicate addresses for you to review.
- **D3**: show both plans: most-efficient-first, and keep-current-mix.
- **Three tabs, in this order: [PTA] [Projections] [Funnel].** The Funnel tab covers the full lead lifecycle: your 15 KPI stages plus Net Leads, your stage-to-stage conversion list, and cost vs profit per stage (spec in §5b). Live Transfer = **Live Transfer Successful**. Profit per stage is shown at both levels: by source (revenue − that source's marketing cost) and company-wide (revenue − all costs).
- **Stack: Streamlit on Streamlit Community Cloud** (free), private app shared with invited emails; projections stored in a free **Neon Postgres**. This replaces the Vercel/Next.js plan, which needed far more setup.

---

## 2. Service account setup (step 0, done by you, ~10 minutes)
1. Go to https://console.cloud.google.com and create a project, e.g. `kpidriver-projections`.
2. Under **APIs & Services → Library**, enable **Google Sheets API**.
3. Under **IAM & Admin → Service Accounts → Create**, name it `projection-reader`. Grant it no roles.
4. Open the account and choose **Keys → Add key → Create new key → JSON**. A file downloads. Keep it private. If key creation is blocked by an org policy, a Workspace admin must allow it for this project.
5. Open the "Projection" sheet → **Share**, and add the service account email (`projection-reader@<project>.iam.gserviceaccount.com`) as **Viewer**, with notifications unchecked. Viewer access, plus the app's `spreadsheets.readonly` scope, means read-only is enforced on Google's side too.
6. Base64-encode the key: `base64 -w0 key.json` (Mac: `base64 -i key.json`).
7. **Local**: put it in `.env` (gitignored) as `GOOGLE_SERVICE_ACCOUNT_JSON_B64=...` and `SHEET_ID=19RJ-hCH0rlOXJpHrnjDY_j_cDu_N4nA2uUuVxagQues`. `DATABASE_URL` is optional locally; without it the app uses a local SQLite file in `.data/`, which is gitignored.
8. **This cloud session**: add `GOOGLE_SERVICE_ACCOUNT_JSON_B64` as an environment variable in the cloud environment settings (session title bar → environment → Edit). A new session picks it up. `sheets.googleapis.com` is already reachable from here. **Never paste the key into chat.**

**Later, at the first deploy (end of Phase c, ~10 minutes):**
9. **Neon**: sign up at neon.tech → create a project → copy the connection string. This becomes `DATABASE_URL`.
10. **Streamlit Community Cloud**:
    - Go to share.streamlit.io, sign in with GitHub and authorize access to `a-ramy/projection`.
    - Choose **New app**: repo `a-ramy/projection`, the branch, main file `app.py`.
    - Under **Advanced settings → Secrets**, paste the three values (key, sheet ID, database URL) as TOML.
    - Click **Deploy**.
    - Then under **Settings → Sharing**, set the app to **private** and invite your team's emails. Viewers sign in with Google or email; there is no OAuth client to configure.

---

## 3. Stack: Streamlit on Streamlit Community Cloud
- **Python 3.12 + Streamlit**, one codebase for the UI and logic, deployed free on Streamlit Community Cloud. Your team opens a URL; the app is **private** and only invited emails can view it. Free apps sleep after a stretch with no visitors and take ~30 s to wake.
- **pandas** for the metrics engine and **pytest** for tests. **gspread** with `google-auth` for Sheets reads, using the `spreadsheets.readonly` scope only.
- **SQLAlchemy** storage behind one `DATABASE_URL`: free **Neon Postgres** in the cloud, a local SQLite file in `.data/` when unset. **pydantic** validates the stored projection documents.
- **Plotly** for charts. `st.data_editor` for the editable projection tables, with a checkbox column per row to accept a suggestion. Read-only tables are styled with pandas Styler: dark green headers, a color per source, green/red PVA.
- **uv** for development (`pyproject.toml`), plus a generated `requirements.txt` for Community Cloud. **ruff** for lint and format.
- Tradeoffs vs Next.js, which you accepted: a less custom look, a full rerun per interaction, and cells you are typing into can't be colored.

## 4. Architecture

```
Google Sheet ──(gspread batch_get, read-only)──► projection/sheets.py
   COSTS!A:C, REVENUES!A:J, KPIs!A:J + KPIs!M   ← K:L (name/phone) are NEVER fetched in bulk; M (GHL link) is
                                                  hashed in memory to a lead_key, and the raw link is discarded
        │  UNFORMATTED values + serial dates, converted with the spreadsheet's timezone
        ▼
projection/data/parse → clean → filter(date >= START_DATE) → month 'YYYY-MM'   (filter as the first step)
        │                └► data/validate.py → list[ValidationIssue] (shown on a Data Quality page)
        ▼
@st.cache_data(ttl=10 min) holds the cleaned 2026+ frames in memory; the "Refresh data" button clears it
        ▼
projection/metrics/*   (pure pandas functions, monthly grain → rolled up by periods.py)
projection/suggest/*   (D1–D3 + guardrails, pure functions)
        ▼
pages/: [PTA] [Projections] [Funnel]   + Settings, Data Quality, Backtest   (st.navigation; entry = app.py)
```

The engine (`projection/`) has no Streamlit imports, so it is unit-testable and reusable from scripts.

**Key modules**
- `projection/config.py`: reads env vars or `.env` (python-dotenv) first, then `st.secrets`. Holds `START_DATE` (default 2026-01-01, overridable in Settings).
- `projection/periods.py`: `Period(grain, key, label, months)` and `rollup(grain)` for month and quarter. Half-year and year are additional grain entries, with no restructuring. It also provides:
  - `completed_months(today)`
  - `cost_complete_through(costs, today)`: the last completed month that has cost rows posted. If a completed month has none, it raises a "costs for <month> not posted yet" notice.
- `projection/data/schema.py` defines three frames (dataclasses or typed DataFrame columns). `addr_key` is a normalized street key; the raw KPI address, name and phone are never cached.
  - Costs: `month, source, cost, sheet_row`
  - Revenues: `date, month, address, source, revenue, exit, agent, fus, acq, dispo, dispo_lm, sheet_row`
  - KPIs: `date, month, created, kpi, quality, stage, acq, source, fus, lead_agent, addr_key, lead_key, sheet_row`. `lead_key` is a one-way hash of the GHL contact ID, so one lead's KPI events can be linked for cohort conversions without keeping any identifier. If the link is blank, it falls back to `addr_key`.
- `projection/metrics/`: `costs.py`, `revenue.py`, `leads.py`, `follow_up.py`, `profit.py`, `pacing.py`, `pta.py`, `cohort.py`, `funnel.py`.
- `projection/funnel_config.py`: `FUNNEL_STAGES`, which lists the main path and the leakage stages, and `CONVERSIONS`, which is **your exact list of pairs** with spelling normalized ("Conract", "Rejeceted"). Adding or removing a conversion is a one-line edit.
- `projection/suggest/`: `lookback.py`, `marketing.py` (D1 + reverse), `revenue.py` (D2), `profit_target.py` (D3, both plans), `guardrails.py`.
- `projection/storage.py` defines three tables:
  - `settings` (key → JSON): start date, non-marketing names, % base exclusions, CPL basis, confidence thresholds, scale cap of 1.5, source colors.
  - `quarter_projections` (quarter_id, status).
  - `projection_revisions` (quarter_id, saved_at, saved_by, payload JSON, append-only). This is the per-quarter history; the latest revision is the current one. `saved_by` comes from `st.user.email` when available.
- The projection payload (pydantic) contains:
  - marketing sources and P.Cost per source, with origin `manual | accepted_suggestion` and the suggestion inputs saved at accept time
  - non-marketing P.Cost
  - revenue rows `{block: main|fix_flip|buy_hold, source | FOLLOW_UP, exit, p_deals, p_avg, origins}`
  - lookback choice and profit target
- PII drill-down: a "Show contact details" button fetches specific KPI rows' K:M **live** by sheet row number. It is not cached, logged or stored.
- PTA is driven by `REP_DIMENSIONS = [RepDim('ACQ', kpi_col='acq', rev_col='acq'), RepDim('FUS', ...)]`. Adding Lead Agent or DISPO later is one config entry.

## 5. Metric definitions (for your approval before Phase b)
All metrics are computed per month, then summed to the period. Ratios are recomputed from summed parts, never averaged.

| Metric | Definition |
|---|---|
| Month of a row | COSTS: calendar month of Date. REVENUES: month of Date Closed. KPIs: month of Date (the trigger date), except **All Leads**, which uses the month of Date Created (owner, Step 4). Rows before START_DATE (default 2026-01-01) are dropped at load. |
| Cost(src, P) | Σ COSTS.Cost for exact Source = src in months of P. Blank cost = $… flagged. |
| All Leads(src, P) | # KPI rows with KPI = "Lead", Source = src, **Date Created** in P (≥ START_DATE), whatever the Quality, including Pending (blank Date). A lead counts once, when it came in, and never moves. On Lead rows, Date is the Quality-change date. |
| Net Leads | Lead rows with Quality = "Qualified", by **Date** (the Quality-change date) in P. **Qualification rate** = Net / All. |
| Deals(src, exit, P) | # REVENUES rows (every row = 1 deal, including $… and negative rows) with Date Closed in P. |
| Revenue | Σ Revenue (losses included). **Avg deal size** = Revenue / Deals. Subtotals are weighted: Σrev / Σdeals. |
| CPL / Net CPL | Cost / All Leads; Cost / Net Leads. |
| Leads per deal (LPD) | All-LPD = All Leads / Deals; Net-LPD = Net Leads / Deals. Deals for the source cover all exit strategies (main + F&F + B&H). |
| Suggested budget | target deals × LPD × CPL, which equals target deals × cost per deal (cost ÷ deals in the window). It is identical on an All or Net lead basis. The explanation shows both calculations, and the implied leads (all and net) = budget ÷ CPL. Target deals = Σ the source's P.Deals across all its revenue rows in all blocks. **Test:** $30,000 / $150 → 200 leads; 200 / 20 deals → LPD 10; 25 × 10 × 150 = **$37,500**. |
| Reverse (override) | implied leads = budget / CPL; implied deals = implied leads / LPD. |
| Follow Up (per block) | Actuals = REVENUES rows in that block whose Source has **no row in that block** of this quarter's projection, split by exit strategy. Drill-down lists the contributing sources. A projected source that closes a deal under an exit strategy it has no row for gets an auto "(unprojected)" actual-only row under that source, so totals reconcile. |
| Other marketing (unprojected) | Σ actual cost of marketing-classified names not selected this quarter. |
| P.% / A.% | P.Cost / projected revenue base; A.Cost / actual revenue base, where an in-progress quarter uses revenue from the same cost-complete months as the costs. The base is total revenue minus excluded exits (default: F&F and B&H). PVA.Cost = P − A; PVA.% = P.% − A.%. Green when ≥ 0 (under budget), red when < 0. |
| Profit / margin | Revenue (all blocks) − total cost; margin = profit / total revenue. |
| Pacing (QTD) | Revenue and KPIs: actual to today vs projected × (days elapsed / days in quarter). Costs: actual through the last cost-complete month vs P.Cost × (complete months / 3), labeled "costs through <month>". |
| EOQ forecast | Revenue: QTD / days elapsed × quarter days. Cost: average of complete months × 3. If no month is complete yet (e.g. Q4 today), projected cost is used and labeled so. |
| Lead→deal (period) | Deals in P / All Leads in P (default). |
| Lead→deal (cohort) | Of addresses with a Lead KPI in month m, the share whose normalized street matches a REVENUES row closed on or after the lead date. Recent cohorts are flagged as immature. |
| Suggestion D2 | Per source × exit over the lookback: P.Deals = deals / quarters in window; P.Avg = window avg deal size. Follow Up uses pooled history of the sources that would roll into it. The historical inputs are shown. |
| Lookback | Whole completed months ≥ START_DATE (cost-complete). Default = last completed quarter. Other options: last 2 quarters, all since start, custom month range. The months used are displayed. |
| Guardrails | *Insufficient data* if leads = 0 or deals = 0 in the window. *Low confidence* if leads < 30 or deals < 3. Both thresholds are settings. *Scale flag* if suggested budget > 1.5 × the source's highest quarterly spend since start. Hover/click shows the formula and inputs. |
| D3 | Non-marketing costs are fixed at the projected values. Follow Up, F&F and B&H are fixed at their projected or suggested values. Needed marketing-source contribution = target profit + fixed costs − fixed revenue. **Plan A**: add deals to the source with the lowest cost per deal (CPL × LPD) that still has positive contribution (avg deal size − cost per deal), up to its 1.5× cap, then the next source. **Plan B**: scale all projected source deals by one factor k. Each plan shows deals and budget per source and any shortfall. |

## 5b. Funnel tab (lead lifecycle)
**Stages**
- **Main path:** Lead → **Net Lead** (Lead with Quality = Qualified) → Lead Assigned → Appointment Set *or* Live Transfer Successful → Appointment Held → Offer Made → Contract Sent → Contract Signed → Closed Deal.
- **Leakage branches:** Live Transfer Unsuccessful, No-show, Appointment Cancelled, Rejected Offer, Contract Rejected, Cancelled Deal.
- Phase a checks that every stage name exists verbatim in the KPI column, and reports any KPI values that aren't on your list.

**Filters:** source (one, several, or all), rep dimension (ACQ/FUS) and rep, period (month or quarter, same period engine), and conversion method (period or cohort).

| Metric | Definition |
|---|---|
| Count(stage, P) | # KPI rows with KPI = stage (case-insensitive) and Date in P, after filters. Lead uses the All Leads rule (Date Created); Net Lead uses the Net Leads rule. Contract Rejected counts the KPI only, not the nurture Stage. |
| Closed Deal | KPI "Closed Deal" count shown **next to** the REVENUES deal count for the same filters, with any mismatch flagged. Revenue and profit always come from REVENUES. |
| Conversion A→B (period, default) | Count(B, P) / Count(A, P). Every pair in your list, e.g. Appointment Set → Appointment Held. "Live Transfer" means Successful. |
| Conversion A→B (cohort) | Of the leads (lead_key) that hit A in month m, the share that hit B on or after that date, at any later time but never before START_DATE. Recent months are flagged immature. |
| Cost per stage | Marketing cost of the filtered sources in P / Count(stage). The company-wide view also shows **all-in cost per stage** (total cost incl. payroll / count). Costs only cover cost-complete months, as elsewhere. Cost is hidden under a rep filter, because costs aren't attributable to reps. |
| Revenue per stage | REVENUES revenue (filtered sources, P) / Count(stage). |
| Profit per stage | **By source:** (revenue − that source's marketing cost) / count. **Company-wide:** (revenue − all costs) / count. Shown as cost-per vs profit-per side by side. |

**Display**
- A funnel chart of the main path with drop-off percentages, and leakage stages branching off.
- A **conversion matrix** heatmap (from-stage rows × to-stage columns), filled only for your listed pairs.
- A stage table: count, conversion from the previous stage and from Lead, cost per stage, revenue per stage, profit per stage.
- Monthly trend lines for any selected conversion.

**Tests (Phase b):** a fixture with known stage counts checks counts, the Net Lead split, period and cohort conversions, cost/revenue/profit per stage at both levels, and the KPI-vs-REVENUES Closed Deal comparison.

## 5c. New names in the sheet are picked up automatically
Nothing is hard-coded. Sources, cost categories, exit strategies, KPI types and reps are all discovered from the sheet on every refresh: on page load when the cache is older than 10 minutes, or immediately with the **Refresh data** button.

| New name appears in… | What happens automatically |
|---|---|
| COSTS (new source) | Treated as **marketing** unless it is on the non-marketing list in Settings. Its spend shows on **Other marketing (unprojected)** with a breakdown, so totals still reconcile. It appears in the "add source" picker and is flagged "New name detected" on the Data Quality page and in a banner, together with the near-duplicate spelling check. A new *non-marketing* line, e.g. a new payroll category, shows as marketing until you tick it as non-marketing in Settings. The banner prompts you. |
| REVENUES (new source) | Rolls into **Follow Up** for any quarter that doesn't give it its own row, and is listed in the Follow Up drill-down. |
| KPIs (new source) | Counted in PTA and the Funnel right away, and added to the source filters. |
| New exit strategy | Gets its own Source × Exit rows in actuals and is flagged. |
| New KPI type | Counted in PTA and flagged. It joins the funnel once added to `FUNNEL_STAGES` (one-line change). |
| New rep (ACQ/FUS) | Appears in PTA filters, charts and the leaderboard. |

**Not automatic, on purpose:** a quarter's projected source list. You choose which sources to project; new ones are offered in the picker and surfaced via "unprojected", never silently added. Saved past quarters keep their lists, while their actuals always recompute from the live sheet. A brand-new source has little history, so its suggestions show "insufficient data" until the lookback window covers enough months.

## 5d. Branding: Total Cash Home Buyers
Source: the TCHB token set from your earlier Claude Design "PTA Production Trend Analysis" page. Your saved Design System artifact turned out to be empty.
- **Colors:**
  - Victoria indigo `#4D458A`: table headers, headings, selected controls
  - Cardinal red `#BD2239`: primary buttons, active tab, section badges
  - Stiletto `#992849`: hover
  - Salem green `#109648`: money and pacing; under-budget PVA uses green-600 `#0D7A3B`, over-budget uses red
  - Neutrals: the gray-050…900 scale
  - Overrides are marked in orange so they never clash with the brand's good/bad colors.
- **Type:** Baloo 2 for display (headings, tabs, big numbers) and Nunito Sans for body and tables, both from Google Fonts. The token notes say these stand in for the wordmark font, so they get replaced if you have the real brand font files.
- **Shape:** radius 6, 10 and 16 px; soft indigo-cast card shadows; the brand gradient (red → indigo) on the logo tile.
- **Logo:** not yet included. Extracting it from the old page was blocked, so you'll send the logo file (SVG or PNG) and it goes in `assets/`.
- **UI style: frosted "liquid glass", futuristic and smooth** (shown in the mockup):
  - Surfaces: translucent, blurred panels (`backdrop-filter`) over a soft red/indigo/green brand-glow backdrop.
  - Controls: pill-shaped glass buttons with a specular highlight (the primary button is a glossy Cardinal red), a floating capsule for the tabs, iOS-style segmented controls with a white glass "thumb", and glass pill dropdowns with a custom chevron.
  - Detail: glossy gradient bars and short ease-out transitions (press-scale, hover lift, a quick entrance on tab change). All motion is turned off for users with reduced-motion set.
  - **Title Case:** every word of interface text starts with a capital (headings, labels, buttons, tabs, dropdowns, notes, table headers), applied globally with CSS `text-transform: capitalize`. Data values keep their own spelling and typed fields are untouched.
  - **Smooth hover rules:** no control container clips its children (no `overflow: hidden` on tab and segmented capsules). Selected and unselected states use the same font weight, so nothing shifts. Hover is a 1 px lift plus a shadow and a press is a 0.97 scale, with one easing curve throughout.
  - **Light / Dark toggle** at the top of the sidebar: a glass segmented switch with sun and moon icons and a smooth cross-fade. It starts from the device setting and remembers each person's choice. In Streamlit it is a sidebar toggle stored in `st.session_state`, which swaps the injected light or dark token set and matching chart template.
- **What Streamlit can reproduce:** most of it, through the injected stylesheet targeting Streamlit's widget classes: panels, buttons, tabs, radio-as-segmented controls, inputs, tables, charts. Two exceptions:
  - The open list of a dropdown is drawn by Streamlit's widget library and will only partly take the glass style.
  - The "Accept" buttons inside tables become a checkbox column.
  - Styling Streamlit's internal classes can break on a Streamlit upgrade, so the Streamlit version is pinned and the CSS kept in one file (`projection/ui/brand.css`).
- **In Streamlit:** `.streamlit/config.toml` theme carries the core colors and fonts (`primaryColor` #BD2239, `textColor`, background colors, `font`/`headingFont` via `[[theme.fontFaces]]`). A small injected stylesheet (`ui/brand.css`) handles the sheet-style table headers, badges and override marking. Tokens live in one file, `projection/ui/brand.py`, so a rebrand is a one-file change.

## 6. Build phases (pause for review after each)
- **0. Setup**: scaffold `pyproject.toml` (uv), `app.py`, `projection/`, `pages/`, `tests/`. Add `.gitignore` (`.env`, `.streamlit/secrets.toml`, `.data/`, any CSV/XLSX/JSON dumps), config loading and SQLAlchemy storage. You set up the service account.
- **a. Data**: Sheets fetch, parse, 2026+ filter, monthly grouping, validation, cache. Then `scripts/profile.py`, which prints aggregates only, and **the full data report for REVENUES and KPIs**:
  - distinct KPI / Quality / Stage values
  - exit strategies, sources per tab, near-duplicate spellings, months covered
  - blank KPI Dates
  - duplicate addresses, $… and negative rows
  - revenue sources with no KPI leads
  - address match rate

  → **Your review**, then I finalize the metric definitions (funnel KPIs are defined only after you see the values).
- **b. Metrics engine + tests**: pytest on a small hand-built fixture with known answers. Covers:
  - the $37,500 case and its reverse
  - Follow Up roll-up per block, including the "(unprojected)" exit row
  - start-date exclusion, the 6/27 month bucketing, blank rows
  - the % base setting, pacing with zero completed cost months
  - guardrail flags, D3 both plans
  - PTA period ratio and cohort
  - the funnel: stage counts, Net Leads, all listed conversions (period and cohort), cost/profit per stage
- **c. Projections tab**: quarter selector (Q1 2026 →), Costs and Revenue tables mirroring your sheet, add/remove sources (from data names or typed), month-by-month breakdown, profit summary and pacing, saved revisions. Then the **first deploy** to Streamlit Community Cloud with Neon (setup steps 9–10).
- **d. Suggestions**: suggested-value column, one-click accept, override marking (overrides always win; never silent overwrite), lookback picker, D3 panel, guardrail badges, formula popovers.
- **e. PTA tab, then Funnel tab** (§5b): ACQ/FUS toggle; rep, source and period filters; monthly/quarterly; KPI counts by type; Q/DQ and qualification rate; deals, revenue, avg size, conversion (period and cohort); trend charts; period-over-period arrows; leaderboard.
- **f. Polish**: charts, colors per source, quarter history browser, Data Quality page; README.md and CLAUDE.md (date rules, marketing split, Follow Up rule, metric definitions, privacy and conventions).
- **First real run**: Q4 2026 suggestions from Q1–Q3, with Q4 actuals to date (no Q4 cost month complete yet; labeled) and pacing.
- **Backtest**: suggestions for Q3 from Q1–Q2 only, compared with Q3 actuals per source on budget, leads, deals and revenue. Shows abs/% error and an overall MAPE, as a page plus `scripts/backtest.py`.

## 7. Verification
- `uv run pytest`: fixture tests with exact expected numbers, including $37,500 and Follow Up. `uv run ruff check`.
- `uv run python scripts/profile.py`: runs against the live sheet and prints only aggregate counts. Totals are cross-checked against the COSTS figures above, e.g. Q3 cost = $… and PPC NW RDS 2026 = $….
- `uv run streamlit run app.py --server.headless true`: drive the UI with Playwright (Chromium is preinstalled), screenshot all three tabs, and check that the Q4 page reconciles: the sum of lines equals the Total, and Follow Up plus named sources equals all revenue.
- Confirm only the `spreadsheets.readonly` scope is used, `git status` never shows data or secret files, and logs contain no names or phones.
- After the first deploy, open the Community Cloud URL as an invited viewer and as a non-invited account, which must be blocked.

## 8. Still to confirm in Phase a (needs the live REVENUES/KPIs data)
- The 2026 duplicate-address list. Counting is already decided (every row is a deal); this is a sanity check for you.
- The distinct KPI, Quality and Stage values, checked against your 15 funnel stages. Funnel and PTA metric definitions are finalized after you see them.
- How many blank-Date KPI rows there are, and the Quality values on them.
- Near-duplicate source spellings across the three tabs, and revenue sources that have no KPI leads.
