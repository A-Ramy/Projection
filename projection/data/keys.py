"""Join keys: normalized street address, hashed lead identity, and spelling-insensitive name key."""

from __future__ import annotations

import hashlib
import re

_SUFFIX = {
    "street": "st", "avenue": "ave", "av": "ave", "road": "rd", "drive": "dr", "court": "ct",
    "lane": "ln", "boulevard": "blvd", "terrace": "ter", "terr": "ter", "place": "pl", "circle": "cir",
    "parkway": "pkwy", "highway": "hwy", "trail": "trl", "square": "sq", "cove": "cv",
}
_DIRECTION = {
    "north": "n", "south": "s", "east": "e", "west": "w",
    "northwest": "nw", "northeast": "ne", "southwest": "sw", "southeast": "se",
}
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")


def addr_key(address: str) -> str:
    """Street part of an address, normalized: '3060 SE Fairmont Street, Stuart FL' -> '3060 se fairmont st'.

    REVENUES holds street-only addresses while KPIs holds full ones, so only the text before the
    first comma is kept. Matching beyond that is a prefix test (see street_matches).
    """
    if not address:
        return ""
    street = address.split(",")[0].casefold().replace("#", " ")
    tokens = _NON_ALNUM.sub(" ", street).split()
    return " ".join(_DIRECTION.get(t, _SUFFIX.get(t, t)) for t in tokens)


def street_matches(revenue_key: str, kpi_key: str) -> bool:
    """True when the REVENUES street key is the KPI street key or a whole-token prefix of it."""
    if not revenue_key or not kpi_key:
        return False
    return kpi_key == revenue_key or kpi_key.startswith(revenue_key + " ")


_CONTACT_ID = re.compile(r"/contacts/(?:detail/)?([A-Za-z0-9_-]+)")


HASHED = "lead_key:"  # marks a link already replaced by its lead_key (data.load.scrub)


def lead_key(ghl_link: str) -> str:
    """One-way hash of the GoHighLevel contact (from its link). The link itself is never kept."""
    if not ghl_link:
        return ""
    text = str(ghl_link).strip()
    if text.startswith(HASHED):
        return text[len(HASHED):]
    m = _CONTACT_ID.search(text)
    ident = m.group(1) if m else text.split("?")[0].split("#")[0].rstrip("/").casefold()
    return hashlib.sha256(ident.encode("utf-8")).hexdigest()[:16]


def name_key(name: str) -> str:
    """Spelling-insensitive key used only to *detect* near-duplicate names (never to join)."""
    text = re.sub(r"\s+", " ", name or "").strip().casefold()
    return re.sub(r"\s*([()&/-])\s*", r"\1", text)
