"""Projecting a quarter from its projection base: the actuals of the quarter before (or a longer window you pick).

Every source starts pre-filled from the base. For each source you type ONE number and the rest follows from the
base's economics for that source (cost per deal, average deal size). Deals are whole: a typed spend or revenue is
rounded to the nearest whole deal and the spend is then deals × cost per deal (owner, 2026-10-19):
    spend   -> deals = round(spend ÷ cost per deal)
    revenue -> deals = round(revenue ÷ avg deal)
    deals   -> as typed (whole)
    exits   -> deals = the sum of the source's exit rows (after you edit an exit row)
    manual  -> spend, deals and revenue each typed (sources with no history)
then spend = deals × cost per deal. The deals are placed on the source's exit rows (Source × Exit) in their current
mix (largest remainder, so 4 Novation : 12 Wholesale + 1 deal = 4 : 13); rows with no deals take the base's mix.
A source's projected revenue = its exit rows' revenue (+ deals that have no exit row × its avg deal).

Sources: the active sources (setting active_sources, in that order), each projected on its own (no-cost ones such
as SELF GEN and Referral by revenue or deals), and Follow Up: one group for every other source.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from projection.data.load import Dataset
from projection.data.schema import block_of
from projection.metrics.core import cost_complete_months, in_months, ratio
from projection.model import BLOCKS, FOLLOW_UP, CostLine, Driver, QuarterProjection, RevenueLine
from projection.periods import Month, Period
from projection.suggest.lookback import label
from projection.suggest.quarter import history_months

MARKETING, NO_COST, FOLLOW_UP_KIND = "marketing", "no_cost", "follow_up"


@dataclass(frozen=True)
class Unit:
    """A source's backbone: per-quarter amounts over the window, and the ratios used to derive the projection."""

    source: str
    cost: float = 0.0  # per quarter
    leads: float = 0.0
    deals: float = 0.0
    revenue: float = 0.0
    cpd: float | None = None  # cost per deal (0 for a source that never spends)
    avg: float | None = None  # avg deal size
    fallback: bool = False  # cpd / avg came from the longer window (no deals in the backbone)
    exits: dict[str, tuple[float, float | None]] = field(default_factory=dict)  # exit -> (deals/quarter, avg)

    @property
    def cpl(self) -> float | None:
        return ratio(self.cost, self.leads)


@dataclass
class Backbone:
    months: list[Month]
    longer: list[Month]  # every cost-complete month before the quarter (fallback window)
    units: dict[str, Unit]

    @property
    def label(self) -> str:
        return label(self.months)

    @property
    def quarters(self) -> float:
        return len(self.months) / 3


def _rows(ds: Dataset, months: list[Month], sources: set[str] | None, exclude: set[str] | None = None):
    c, r, k = in_months(ds.costs, months), in_months(ds.revenues, months), in_months(ds.leads, months)
    if sources is not None:
        c, r, k = (df[df["source"].isin(sources)] for df in (c, r, k))
    if exclude is not None:
        c, r, k = (df[~df["source"].isin(exclude)] for df in (c, r, k))
    return c, r, k


def _unit(ds: Dataset, source: str, months: list[Month], longer: list[Month], sources: set[str] | None,
          exclude: set[str] | None = None) -> Unit:
    q = len(months) / 3 or 1
    c, r, k = _rows(ds, months, sources, exclude)
    cost, deals, revenue = float(c["cost"].sum()), len(r), float(r["revenue"].sum())
    exits = {e: (len(g) / q, ratio(float(g["revenue"].sum()), len(g))) for e, g in r.groupby("exit") if e}
    cpd, avg, fallback = ratio(cost, deals), ratio(revenue, deals), False
    if not deals:
        lc, lr, _ = _rows(ds, longer, sources, exclude)
        l_cost, l_deals = float(lc["cost"].sum()), len(lr)
        cpd, avg = ratio(l_cost, l_deals), ratio(float(lr["revenue"].sum()), l_deals)
        fallback = l_deals > 0
        if not l_cost and not cost:
            cpd = 0.0  # a source that never spends
    if exclude is not None:
        cost, cpd = 0.0, 0.0  # Follow Up has no spend of its own
    return Unit(source, cost / q, (len(k) if exclude is None else 0) / q, deals / q, revenue / q, cpd, avg,
                fallback, exits)


def backbone(ds: Dataset, p: QuarterProjection, period: Period) -> Backbone:
    months = history_months(ds, period, p)
    longer = [m for m in cost_complete_months(ds) if m.last_day < period.start]
    units = {c.source: _unit(ds, c.source, months, longer, {c.source}) for c in p.marketing}
    units[FOLLOW_UP] = _unit(ds, FOLLOW_UP, months, longer, None, exclude=p.projected_sources())
    return Backbone(months, longer, units)


@dataclass
class SourceRow:
    source: str
    kind: str  # marketing | no_cost | follow_up
    unit: Unit
    driver: Driver
    spend: float | None
    deals: float | None
    revenue: float | None
    allocated_deals: float
    allocated_revenue: float

    @property
    def unallocated(self) -> float | None:
        return None if self.deals is None else self.deals - self.allocated_deals

    @property
    def roas(self) -> float | None:
        return ratio(self.revenue, self.spend) if self.revenue is not None and self.spend else None

    @property
    def notes(self) -> list[str]:
        out = []
        d = self.driver
        if d.typed and d.kind in ("spend", "revenue") and self.deals is not None:
            out.append(f"Typed {d.kind} ${d.value:,.0f} → {self.deals:,.0f} whole deals")
        if self.unit.fallback and self.driver.typed:
            out.append("Cost per deal and avg deal from the longer window (no deals in the base)")
        elif self.unit.fallback:
            out.append("No deals in the base: type its spend or deals to use the longer window's cost per deal")
        elif self.deals is None:
            out.append("No history: tick Manual and type its spend, deals and revenue")
        if self.unallocated is not None and abs(self.unallocated) >= 0.05:
            out.append(f"{self.unallocated:+,.0f} deals with no exit row (add one in table 2)")
        return out


def whole(x: float) -> int:
    """Nearest whole deal (halves round up), never below 0."""
    return max(0, math.floor(x + 0.5 + 1e-9))


def spread(total: int, weights: list[float]) -> list[int]:
    """`total` whole deals split in proportion to `weights` (largest remainder; equal split if all weights are 0)."""
    if not weights:
        return []
    if sum(weights) <= 0:
        weights = [1.0] * len(weights)
    s = sum(weights)
    raw = [total * w / s for w in weights]
    out = [math.floor(x + 1e-9) for x in raw]
    for i in sorted(range(len(raw)), key=lambda i: (out[i] - raw[i], -weights[i]))[: max(0, total - sum(out))]:
        out[i] += 1
    return out


def derive(driver: Driver, unit: Unit, allocated: float,
           allocated_revenue: float = 0.0) -> tuple[float | None, float | None, float | None]:
    """(spend, deals, revenue) for a source from its driver, its base and its exit rows."""
    if driver.kind == "manual":
        return driver.spend, driver.deals, driver.revenue
    v, cpd, avg = driver.value, unit.cpd, unit.avg
    if unit.fallback and not driver.typed:
        cpd = avg = None  # the pre-filled base repeats what happened: spend with no deals
    if driver.kind == "spend":
        deals = whole(v / cpd) if cpd else None
    elif driver.kind == "revenue":
        deals = whole(v / avg) if avg else None
    elif driver.kind == "deals":
        deals = whole(v)
    else:
        deals = allocated
    if deals is None:
        spend = v if driver.kind == "spend" else None
        revenue = v if driver.kind == "revenue" else None
        return spend, None, revenue
    spend = deals * cpd if cpd is not None else None
    # placed deals at their exit's avg, any without an exit row at the source's avg
    revenue = allocated_revenue + (deals - allocated) * (avg or 0)
    return spend, deals, revenue


def source_rows(p: QuarterProjection, bb: Backbone, settings: dict) -> list[SourceRow]:
    out = []
    saved_cost = {c.source: c.p_cost for c in p.marketing}
    for src in [c.source for c in p.marketing] + [FOLLOW_UP]:
        lines = [r for r in p.revenue if r.source == src]
        if src == FOLLOW_UP and not lines and FOLLOW_UP not in p.drivers:
            continue
        unit = bb.units.get(src) or Unit(src)
        alloc_d, alloc_r = sum(r.p_deals for r in lines), sum(r.p_revenue for r in lines)
        # a projection saved before drivers existed keeps its saved spend
        driver = p.drivers.get(src) or (Driver(kind="spend", value=saved_cost[src], typed=True)
                                        if saved_cost.get(src) else Driver())
        spend, deals, revenue = derive(driver, unit, alloc_d, alloc_r)
        kind = FOLLOW_UP_KIND if src == FOLLOW_UP else (NO_COST if unit.cpd == 0 else MARKETING)
        out.append(SourceRow(src, kind, unit, driver, spend, deals, revenue, alloc_d, alloc_r))
    return out


def sync_costs(p: QuarterProjection, bb: Backbone, settings: dict) -> None:
    """Projected spend on each marketing line follows its driver."""
    spend = {r.source: r.spend for r in source_rows(p, bb, settings)}
    for c in p.marketing:
        c.p_cost = round(spend.get(c.source) or 0.0, 2)
        c.origin = "manual"


def place(p: QuarterProjection, source: str, deals: int, unit: Unit | None, avg: float | None = None) -> None:
    """Put a source's whole deals on its exit rows in their current mix; rows with no deals yet take the base's mix
    (adding the rows it needs). A source with no exit rows and no base mix keeps its deals unplaced."""
    lines = [r for r in p.revenue if r.source == source]
    weights = [r.p_deals for r in lines]
    if not sum(weights) and unit is not None and unit.exits:
        have = {r.exit for r in lines}
        for exit_, (_, a) in unit.exits.items():
            if exit_ not in have:
                line = RevenueLine(block=block_of(exit_), source=source, exit=exit_, p_avg=round(a or 0, 2))
                p.revenue.append(line)
                lines.append(line)
        weights = [unit.exits.get(r.exit, (0.0, None))[0] for r in lines]
    for line, n in zip(lines, spread(deals, weights), strict=True):
        line.p_deals = float(n)
        if avg is not None:
            line.p_avg = round(avg, 2)
    _sort(p)


def link(p: QuarterProjection, source: str, bb: Backbone) -> None:
    """After a source's driver changes: its exit rows follow its new number of deals."""
    d = p.drivers.get(source)
    if d is None or d.kind == "exits":
        return
    unit = bb.units.get(source)
    if d.kind == "manual":
        place(p, source, whole(d.deals), unit, avg=d.revenue / d.deals if d.deals else None)
        return
    lines = [r for r in p.revenue if r.source == source]
    _, deals, _ = derive(d, unit or Unit(source), sum(r.p_deals for r in lines), sum(r.p_revenue for r in lines))
    if deals is not None:
        place(p, source, int(deals), unit)


def relink(p: QuarterProjection, bb: Backbone, settings: dict) -> list[str]:
    """Put back in step every source whose exit rows don't add up to its deals (e.g. a version saved before deals
    were whole and linked): its whole deals are re-placed on its rows in their current mix. Returns those sources."""
    fixed = []
    for r in source_rows(p, bb, settings):
        d = p.drivers.get(r.source)
        if d is None or d.kind == "exits" or r.deals is None or r.unallocated is None:
            continue
        has_rows = any(x.source == r.source for x in p.revenue) or bool(r.unit.exits)
        fractional = any(x.p_deals != int(x.p_deals) for x in p.revenue if x.source == r.source)
        if has_rows and (abs(r.unallocated) >= 0.5 or fractional):
            link(p, r.source, bb)
            fixed.append(r.source)
    if fixed:
        sync_costs(p, bb, settings)
    return fixed


def set_driver(p: QuarterProjection, source: str, kind: str, value: float, bb: Backbone, settings: dict) -> None:
    p.drivers[source] = Driver(kind=kind, value=float(value), typed=True)
    link(p, source, bb)
    sync_costs(p, bb, settings)


def set_manual(p: QuarterProjection, source: str, bb: Backbone, settings: dict, spend: float | None = None,
               deals: float | None = None, revenue: float | None = None) -> None:
    """Type a source's spend, deals and revenue freely (nothing is worked out). Turning it on starts from what the
    source shows now; avg deal on its exit rows = revenue ÷ deals."""
    d = p.drivers.get(source)
    if d is None or d.kind != "manual":
        row = next((r for r in source_rows(p, bb, settings) if r.source == source), None)
        d = Driver(kind="manual", typed=True, spend=(row.spend or 0) if row else 0,
                   deals=(row.deals or 0) if row else 0, revenue=(row.revenue or 0) if row else 0)
    if spend is not None:
        d.spend = float(spend)
    if deals is not None:
        d.deals = float(whole(deals))
    if revenue is not None:
        d.revenue = float(revenue)
    p.drivers[source] = d
    link(p, source, bb)
    sync_costs(p, bb, settings)


def edit_exit(p: QuarterProjection, i: int, bb: Backbone, settings: dict, deals: float | None = None,
              avg: float | None = None, revenue: float | None = None) -> None:
    """An exit row edit. Changing its deals makes the exit rows set the source's deals (and so its spend)."""
    line = p.revenue[i]
    if avg is not None:
        line.p_avg = float(avg)
    if deals is not None:
        line.p_deals = float(whole(deals))
    if revenue is not None and line.p_avg:
        line.p_deals = float(whole(revenue / line.p_avg))
    d = p.drivers.get(line.source)
    lines = [r for r in p.revenue if r.source == line.source]
    if d is not None and d.kind == "manual":
        d.deals = sum(r.p_deals for r in lines)
        d.revenue = sum(r.p_revenue for r in lines)
    elif deals is not None or revenue is not None:
        p.drivers[line.source] = Driver(kind="exits", typed=True)
    sync_costs(p, bb, settings)


def split_by_mix(p: QuarterProjection, source: str, bb: Backbone, settings: dict) -> None:
    """Re-place a source's deals over its exit rows in the base's mix (adds the rows it needs)."""
    row = next((r for r in source_rows(p, bb, settings) if r.source == source), None)
    if row is None or row.deals is None or not row.unit.exits:
        return
    for r in p.revenue:
        if r.source == source:
            r.p_deals = 0.0
    place(p, source, whole(row.deals), row.unit)
    sync_costs(p, bb, settings)


def _sort(p: QuarterProjection) -> None:
    """Exit rows grouped by source in the sources' order (Follow Up last); within a source the order is kept."""
    order = {c.source: i for i, c in enumerate(p.marketing)}
    p.revenue.sort(key=lambda r: (r.source == FOLLOW_UP, order.get(r.source, 999)))


def reorder_exits(p: QuarterProjection, order: list[int]) -> None:
    """Exit rows in this order (indexes into p.revenue); they stay grouped under their source."""
    p.revenue = [p.revenue[i] for i in order] + [r for i, r in enumerate(p.revenue) if i not in set(order)]
    _sort(p)


def prefill(ds: Dataset, period: Period, settings: dict, base: QuarterProjection) -> QuarterProjection:
    """The backbone repeated: every active source (with its backbone spend and exit rows), Follow Up for every other
    source's deals, and the non-marketing lines, each at its per-quarter backbone value. Keeps the base's quarter id
    and backbone choice."""
    p = QuarterProjection(quarter_id=base.quarter_id, lookback=base.lookback, lookback_from=base.lookback_from,
                          lookback_to=base.lookback_to, profit_target=base.profit_target)
    months = history_months(ds, period, p)
    q = len(months) / 3 or 1
    costs, revs = in_months(ds.costs, months), in_months(ds.revenues, months)
    spent = costs.groupby("source")["cost"].sum()
    for src in dict.fromkeys(settings.get("active_sources", [])):
        p.marketing.append(CostLine(source=src))
        if spent.get(src, 0) > 0:
            p.drivers[src] = Driver(kind="spend", value=round(float(spent[src]) / q, 2))
    projected = {c.source for c in p.marketing}
    for (src, exit_), g in revs[revs["exit"] != ""].groupby(["source", "exit"]):
        key_src = src if src in projected else FOLLOW_UP
        line = next((r for r in p.revenue if (r.source, r.exit) == (key_src, exit_)), None)
        if line is None:
            line = RevenueLine(block=block_of(exit_), source=key_src, exit=exit_)
            p.revenue.append(line)
            line.inputs = {"deals": 0, "revenue": 0.0}
        line.inputs["deals"] += len(g)
        line.inputs["revenue"] += float(g["revenue"].sum())
    blocks = {b: i for i, b in enumerate(BLOCKS)}
    p.revenue.sort(key=lambda r: (blocks[r.block], r.exit))
    for src in dict.fromkeys(r.source for r in p.revenue):  # whole deals per source, in the base's mix
        lines = [r for r in p.revenue if r.source == src]
        raw = [r.inputs["deals"] / q for r in lines]
        for line, n in zip(lines, spread(whole(sum(raw)), raw), strict=True):
            line.p_deals = float(n)
            line.p_avg = round(line.inputs["revenue"] / line.inputs["deals"], 2)
            line.inputs = None
    _sort(p)
    nm = in_months(ds.costs, months)
    for name in settings.get("non_marketing", []):
        p.non_marketing.append(CostLine(source=name, p_cost=round(float(nm.loc[nm["source"] == name, "cost"].sum())
                                                                  / q, 2)))
    sync_costs(p, backbone(ds, p, period), settings)
    return p


def add_active_sources(p: QuarterProjection, ds: Dataset, period: Period, settings: dict) -> list[str]:
    """Add the active sources missing from p, each as the backbone would start it (spend driver and exit rows);
    typed values on the other sources are kept. Returns the names added."""
    have = {c.source for c in p.marketing}
    fresh = prefill(ds, period, settings, p)
    added = [c.source for c in fresh.marketing if c.source not in have]
    for src in added:
        p.marketing.append(next(c for c in fresh.marketing if c.source == src))
        if src in fresh.drivers:
            p.drivers[src] = fresh.drivers[src]
        p.revenue += [r for r in fresh.revenue if r.source == src]
    reorder(p, list(dict.fromkeys(settings.get("active_sources", []))))
    sync_costs(p, backbone(ds, p, period), settings)
    return added


def reorder(p: QuarterProjection, order: list[str]) -> None:
    """Put the marketing lines in this order (names not in it keep their place after it); revenue rows follow."""
    pos = {s: i for i, s in enumerate(order)}
    p.marketing.sort(key=lambda c: pos.get(c.source, len(pos)))
    _sort(p)


def use_plan(p: QuarterProjection, plan, bb: Backbone, settings: dict) -> None:
    """A profit-target plan becomes each planned source's deals driver (exit rows stay yours to place)."""
    for x in plan.lines:
        p.drivers[x.source] = Driver(kind="deals", value=whole(x.deals), typed=True)
        link(p, x.source, bb)
    sync_costs(p, bb, settings)


def totals(p: QuarterProjection, rows: list[SourceRow]) -> dict[str, float]:
    marketing = sum(r.spend or 0 for r in rows if r.kind != FOLLOW_UP_KIND)
    non = sum(c.p_cost for c in p.non_marketing)
    placed = sum(r.p_revenue for r in p.revenue)
    revenue = sum(r.revenue if r.revenue is not None else r.allocated_revenue for r in rows)
    deals = sum(r.deals if r.deals is not None else r.allocated_deals for r in rows)
    return {"revenue": revenue, "placed_revenue": placed, "not_placed": revenue - placed, "marketing": marketing,
            "non_marketing": non, "cost": marketing + non, "profit": revenue - marketing - non, "deals": deals}
