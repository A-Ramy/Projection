"""A saved quarter projection: the payload stored as append-only revisions (storage.py), never in the sheet.

Costs are split into marketing sources and non-marketing lines. Revenue lines are Source × Exit rows in
one of three blocks (main, Fix & Flip, Buy & Hold); FOLLOW_UP is the catch-all row of a block.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FOLLOW_UP = "Follow Up"
Block = Literal["main", "fix_flip", "buy_hold"]
BLOCKS: tuple[Block, ...] = ("main", "fix_flip", "buy_hold")
Origin = Literal["manual", "accepted_suggestion", "override"]
DriverKind = Literal["spend", "revenue", "deals", "exits", "manual"]


class CostLine(BaseModel):
    source: str
    p_cost: float = 0.0
    origin: Origin = "manual"
    inputs: dict | None = None  # suggestion inputs saved when accepted


class RevenueLine(BaseModel):
    block: Block
    source: str  # a REVENUES Source, or FOLLOW_UP
    exit: str
    p_deals: float = 0.0
    p_avg: float = 0.0
    origin: Origin = "manual"
    inputs: dict | None = None

    @property
    def p_revenue(self) -> float:
        return self.p_deals * self.p_avg


class Driver(BaseModel):
    """The number typed for a source; the rest of the source is worked out from the backbone's economics.
    spend -> deals = spend ÷ cost per deal; revenue -> deals = revenue ÷ avg deal; deals -> as typed;
    exits -> deals = the sum of the source's exit rows; manual -> spend, deals and revenue each typed (a source with
    no history). Deals are whole: a typed spend or revenue is rounded to the nearest whole deal."""

    kind: DriverKind = "exits"
    value: float = 0.0
    typed: bool = False  # typed by you (a pre-filled base value is not): only typed numbers use the fallback
    spend: float = 0.0  # manual only
    deals: float = 0.0
    revenue: float = 0.0


class QuarterProjection(BaseModel):
    quarter_id: str  # "2026-Q4"
    marketing: list[CostLine] = Field(default_factory=list)
    non_marketing: list[CostLine] = Field(default_factory=list)
    revenue: list[RevenueLine] = Field(default_factory=list)
    lookback: str = "last_quarter"
    lookback_from: str | None = None  # custom lookback, month keys "YYYY-MM"
    lookback_to: str | None = None
    profit_target: float | None = None
    drivers: dict[str, Driver] = Field(default_factory=dict)  # per source, incl. FOLLOW_UP

    def projected_sources(self) -> set[str]:
        """Sources on the projection: a marketing line or a revenue row in any block (Follow Up excluded).
        Only deals from other sources roll into Follow Up."""
        return {c.source for c in self.marketing} | {r.source for r in self.revenue if r.source != FOLLOW_UP}

    def target_deals(self, source: str) -> float:
        """Σ the source's P.Deals across all its revenue rows in all blocks."""
        return sum(r.p_deals for r in self.revenue if r.source == source)

    @property
    def p_cost(self) -> float:
        return sum(c.p_cost for c in self.marketing + self.non_marketing)

    @property
    def p_revenue(self) -> float:
        return sum(r.p_revenue for r in self.revenue)
