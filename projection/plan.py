"""Projecting a quarter from its backbone: the actuals of the quarter before (or a longer window you pick).

Every source starts pre-filled from the backbone. For each source you type ONE number and the rest follows from
the backbone's economics for that source (cost per deal, average deal size):
    spend   -> deals = spend ÷ cost per deal, revenue = deals × avg deal
    revenue -> deals = revenue ÷ avg deal,    spend = deals × cost per deal
    deals   -> spend = deals × cost per deal, revenue = deals × avg deal
    exits   -> deals = the sum of the source's exit rows (the default for no-cost sources and Follow Up)
The deals are then placed on exit rows (Source × Exit, typed by you); any difference shows as not placed.
A source's projected revenue = its exit rows' revenue + deals not yet placed × its avg deal (a typed revenue counts
as typed); projected cost is the derived spend.

Sources: the active sources (setting active_sources, in that order), each projected on its own (no-cost ones such
as SELF GEN and Referral by revenue or deals), and Follow Up: one group for every other source.
"""

from __future__ import annotations

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
    def notes(self) -> list[str]:
        out = []
        if self.unit.fallback and self.driver.typed:
            out.append("Cost per deal and avg deal from the longer window (no deals in the backbone)")
        elif self.unit.fallback:
            out.append("No deals in the backbone: type its spend or deals to use the longer window's cost per deal")
        elif self.deals is None:
            out.append("No cost per deal or avg deal yet: type deals on its exit rows")
        if self.unallocated is not None and abs(self.unallocated) >= 0.05:
            out.append(f"{self.unallocated:+.1f} deals not placed on exit rows")
        return out


def derive(driver: Driver, unit: Unit, allocated: float,
           allocated_revenue: float = 0.0) -> tuple[float | None, float | None, float | None]:
    """(spend, deals, revenue) for a source from its driver, its backbone and its exit rows."""
    v, cpd, avg = driver.value, unit.cpd, unit.avg
    if unit.fallback and not driver.typed:
        cpd = avg = None  # the pre-filled backbone repeats what happened: spend with no deals
    if driver.kind == "spend":
        deals = v / cpd if cpd else None
    elif driver.kind == "revenue":
        deals = v / avg if avg else None
    elif driver.kind == "deals":
        deals = v
    else:
        deals = allocated
    spend = v if driver.kind == "spend" else (deals * cpd if deals is not None and cpd is not None else None)
    if driver.kind == "revenue":
        revenue = v
    elif deals is None:
        revenue = None
    else:  # placed deals at their exit's avg, the rest at the source's avg
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


def set_driver(p: QuarterProjection, source: str, kind: str, value: float, bb: Backbone, settings: dict) -> None:
    p.drivers[source] = Driver(kind=kind, value=float(value), typed=True)
    sync_costs(p, bb, settings)


def split_by_mix(p: QuarterProjection, source: str, bb: Backbone, settings: dict) -> None:
    """Spread a source's derived deals over exit rows in its backbone mix (adds the rows it needs)."""
    row = next((r for r in source_rows(p, bb, settings) if r.source == source), None)
    if row is None or row.deals is None or not row.unit.exits:
        return
    total = sum(d for d, _ in row.unit.exits.values()) or 1
    have = {(r.block, r.exit): r for r in p.revenue if r.source == source}
    for exit_, (d, avg) in row.unit.exits.items():
        key = (block_of(exit_), exit_)
        line = have.get(key)
        if line is None:
            line = RevenueLine(block=key[0], source=source, exit=exit_, p_avg=round(avg or 0, 2))
            p.revenue.append(line)
        line.p_deals = round(row.deals * d / total, 2)
    _sort(p)


def _sort(p: QuarterProjection) -> None:
    order = {c.source: i for i, c in enumerate(p.marketing)}
    blocks = {b: i for i, b in enumerate(BLOCKS)}
    p.revenue.sort(key=lambda r: (r.source == FOLLOW_UP, order.get(r.source, 999), blocks[r.block], r.exit))


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
    for line in p.revenue:
        line.p_deals = round(line.inputs["deals"] / q, 2)
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
        p.drivers[x.source] = Driver(kind="deals", value=round(x.deals, 2), typed=True)
    sync_costs(p, bb, settings)


def totals(p: QuarterProjection, rows: list[SourceRow]) -> dict[str, float]:
    marketing = sum(r.spend or 0 for r in rows if r.kind != FOLLOW_UP_KIND)
    non = sum(c.p_cost for c in p.non_marketing)
    placed = sum(r.p_revenue for r in p.revenue)
    revenue = sum(r.revenue if r.revenue is not None else r.allocated_revenue for r in rows)
    deals = sum(r.deals if r.deals is not None else r.allocated_deals for r in rows)
    return {"revenue": revenue, "placed_revenue": placed, "not_placed": revenue - placed, "marketing": marketing,
            "non_marketing": non, "cost": marketing + non, "profit": revenue - marketing - non, "deals": deals}
