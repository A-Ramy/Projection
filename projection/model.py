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


class QuarterProjection(BaseModel):
    quarter_id: str  # "2026-Q4"
    marketing: list[CostLine] = Field(default_factory=list)
    non_marketing: list[CostLine] = Field(default_factory=list)
    revenue: list[RevenueLine] = Field(default_factory=list)
    lookback: str = "last_quarter"
    lookback_from: str | None = None  # custom lookback, month keys "YYYY-MM"
    lookback_to: str | None = None
    profit_target: float | None = None

    def sources_in_block(self, block: str) -> set[str]:
        """Named sources with a row in the block (Follow Up excluded)."""
        return {r.source for r in self.revenue if r.block == block and r.source != FOLLOW_UP}

    def target_deals(self, source: str) -> float:
        """Σ the source's P.Deals across all its revenue rows in all blocks."""
        return sum(r.p_deals for r in self.revenue if r.source == source)

    @property
    def p_cost(self) -> float:
        return sum(c.p_cost for c in self.marketing + self.non_marketing)

    @property
    def p_revenue(self) -> float:
        return sum(r.p_revenue for r in self.revenue)
