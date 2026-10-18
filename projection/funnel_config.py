"""Lead lifecycle stages and the stage-to-stage conversions to report.

KPI_STAGES are the KPI values from GoHighLevel. "Net Lead" is derived (KPI = Lead with
Quality = Qualified). "Live Transfer" in a conversion means "Live Transfer Successful".
Adding or removing a conversion is a one-line edit to CONVERSIONS.
"""

from __future__ import annotations

NET_LEAD = "Net Lead"
LIVE_TRANSFER = "Live Transfer Successful"

KPI_STAGES = [
    "Lead",
    "Lead Assigned",
    "Appointment Set",
    "Live Transfer Successful",
    "Live Transfer Unsuccessful",
    "Appointment Held",
    "No-show",
    "Appointment Cancelled",
    "Offer Made",
    "Rejected Offer",
    "Contract Sent",
    "Contract Rejected",
    "Contract Signed",
    "Closed Deal",
    "Cancelled Deal",
]

MAIN_PATH = [
    "Lead", NET_LEAD, "Lead Assigned", "Appointment Set", LIVE_TRANSFER,
    "Appointment Held", "Offer Made", "Contract Sent", "Contract Signed", "Closed Deal",
]
LEAKAGE = [
    "Live Transfer Unsuccessful", "No-show", "Appointment Cancelled",
    "Rejected Offer", "Contract Rejected", "Cancelled Deal",
]

_AFTER_OFFER = ["Rejected Offer", "Contract Sent", "Contract Signed", "Contract Rejected", "Closed Deal",
                "Cancelled Deal"]

# (from, to). As listed by the owner, plus the Net Lead pairs marked ADDED.
CONVERSIONS: list[tuple[str, str]] = [
    *[("Lead", t) for t in ["Appointment Set", "Appointment Held", "No-show", "Appointment Cancelled",
                            "Offer Made", "Rejected Offer", "Contract Sent", "Contract Signed",
                            "Contract Rejected", "Closed Deal", "Cancelled Deal"]],
    *[("Appointment Set", t) for t in ["Appointment Held", "No-show", "Appointment Cancelled", "Offer Made",
                                       "Rejected Offer", "Contract Sent", "Contract Rejected",
                                       "Contract Signed", "Closed Deal", "Cancelled Deal"]],
    *[("Appointment Held", t) for t in ["Offer Made", *_AFTER_OFFER]],
    ("Lead", LIVE_TRANSFER),
    *[(LIVE_TRANSFER, t) for t in ["Offer Made", *_AFTER_OFFER]],
    *[("Offer Made", t) for t in _AFTER_OFFER],
    *[("Rejected Offer", t) for t in ["Contract Sent", "Contract Signed", "Closed Deal", "Cancelled Deal"]],
    *[("Contract Sent", t) for t in ["Contract Rejected", "Contract Signed", "Closed Deal", "Cancelled Deal"]],
    *[("Contract Rejected", t) for t in ["Contract Signed", "Closed Deal", "Cancelled Deal"]],
    ("Contract Signed", "Closed Deal"),
    ("Contract Signed", "Cancelled Deal"),
    ("Closed Deal", "Cancelled Deal"),
]
ADDED = [("Lead", NET_LEAD), (NET_LEAD, "Appointment Set"), (NET_LEAD, "Closed Deal")]
ALL_CONVERSIONS = ADDED + CONVERSIONS
