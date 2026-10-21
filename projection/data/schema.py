"""Expected sheet layout and the shared Issue type.

Columns are located by header name (case/space-insensitive), not by position, so a moved column
doesn't silently shift data. Personal columns (Full Name, Phone) are never fetched in bulk.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TAB_COSTS = "COSTS"
TAB_REVENUES = "REVENUES"
TAB_KPIS = "KPIs"

# field name -> sheet header
COSTS_COLUMNS = {"date": "Date", "source": "Source", "cost": "Cost"}
REVENUES_COLUMNS = {
    "date": "Date Closed",
    "address": "Address",
    "source": "Source",
    "revenue": "Revenue",
    "exit": "Exit Strategy",
    "agent": "AGENT",
    "fus": "FUS",
    "acq": "ACQ",
    "dispo": "DISPO",
    "dispo_lm": "DISPO LM",
}
# KPIs A:J only. K (Full Name) and L (Phone) are excluded on purpose.
KPIS_COLUMNS = {
    "date": "Date",
    "created": "Date Created",
    "kpi": "KPI",
    "quality": "Quality",
    "stage": "Stage",
    "acq": "ACQ",
    "source": "Source",
    "fus": "FUS",
    "lead_agent": "Lead Agent",
    "address": "Property Address",
}
KPIS_LINK_HEADER = "GHL Link"

# Sheet ranges fetched in one batch. KPIs!M is hashed in memory into lead_key, then discarded.
RANGES = {
    TAB_COSTS: f"{TAB_COSTS}!A:C",
    TAB_REVENUES: f"{TAB_REVENUES}!A:J",
    TAB_KPIS: f"{TAB_KPIS}!A:J",
    "KPIS_LINK": f"{TAB_KPIS}!M:M",
}

KNOWN_EXITS = ["Novation", "Wholesale", "Retail Listing", "Fix & Flip", "Buy & Hold"]
# Revenue blocks in the Projections tab
BLOCK_OF_EXIT = {"Fix & Flip": "fix_flip", "Buy & Hold": "buy_hold"}  # everything else: "main"

LEAD_KPI = "Lead"
QUALIFIED = "Qualified"
DISQUALIFIED = "Disqualified"
PENDING = "Pending"  # a Lead row that is neither Qualified nor Disqualified (incl. blank)


def block_of(exit_strategy: str) -> str:
    return BLOCK_OF_EXIT.get(exit_strategy, "main")


@dataclass
class Issue:
    severity: str  # "error" | "warning" | "info"
    tab: str
    code: str
    title: str
    detail: str = ""
    count: int = 0
    examples: list[str] = field(default_factory=list)

    SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}

    @property
    def rank(self) -> int:
        return self.SEVERITY_ORDER.get(self.severity, 9)
