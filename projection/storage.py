"""The app's own storage (never the Google Sheet): settings and per-quarter projection history.

Projections are saved as append-only revisions, so every past version of a quarter is kept.
DATABASE_URL selects the database (Neon Postgres in the cloud); unset = SQLite in .data/app.db.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
    select,
    update,
)

from projection.config import DATA_DIR, DEFAULT_SETTINGS

metadata = MetaData()

settings_table = Table(
    "settings", metadata,
    Column("key", String(100), primary_key=True),
    Column("value", JSON, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("updated_by", String(200), nullable=False, default=""),
)

quarters_table = Table(
    "quarter_projections", metadata,
    Column("quarter_id", String(10), primary_key=True),  # e.g. "2026-Q4"
    Column("status", String(20), nullable=False, default="draft"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

revisions_table = Table(
    "projection_revisions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("quarter_id", String(10), nullable=False, index=True),
    Column("saved_at", DateTime(timezone=True), nullable=False),
    Column("saved_by", String(200), nullable=False, default=""),
    Column("note", String(500), nullable=False, default=""),
    Column("payload", JSON, nullable=False),
)


def normalize_url(url: str | None) -> str:
    if not url:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{DATA_DIR / 'app.db'}"
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _now() -> datetime:
    return datetime.now(UTC)


class Store:
    def __init__(self, url: str | None = None):
        self.engine = create_engine(normalize_url(url), pool_pre_ping=True)
        metadata.create_all(self.engine)

    # ---- settings
    def get_settings(self) -> dict:
        with self.engine.connect() as c:
            saved = {r.key: r.value for r in c.execute(select(settings_table))}
        return {**DEFAULT_SETTINGS, **saved}

    def set_setting(self, key: str, value, by: str = "") -> None:
        with self.engine.begin() as c:
            exists = c.execute(select(settings_table.c.key).where(settings_table.c.key == key)).first()
            values = {"value": value, "updated_at": _now(), "updated_by": by}
            if exists:
                c.execute(update(settings_table).where(settings_table.c.key == key).values(**values))
            else:
                c.execute(insert(settings_table).values(key=key, **values))

    # ---- projections
    def save_revision(self, quarter_id: str, payload: dict, by: str = "", note: str = "",
                      status: str | None = None) -> int:
        now = _now()
        with self.engine.begin() as c:
            q = c.execute(select(quarters_table).where(quarters_table.c.quarter_id == quarter_id)).first()
            if q:
                vals = {"updated_at": now, **({"status": status} if status else {})}
                c.execute(update(quarters_table).where(quarters_table.c.quarter_id == quarter_id).values(**vals))
            else:
                c.execute(insert(quarters_table).values(quarter_id=quarter_id, status=status or "draft",
                                                        created_at=now, updated_at=now))
            res = c.execute(insert(revisions_table).values(quarter_id=quarter_id, saved_at=now, saved_by=by,
                                                           note=note, payload=payload))
            return int(res.inserted_primary_key[0])

    def latest_revision(self, quarter_id: str) -> dict | None:
        with self.engine.connect() as c:
            row = c.execute(
                select(revisions_table).where(revisions_table.c.quarter_id == quarter_id)
                .order_by(revisions_table.c.id.desc()).limit(1)
            ).first()
        return dict(row._mapping) if row else None

    def get_revision(self, revision_id: int) -> dict | None:
        with self.engine.connect() as c:
            row = c.execute(select(revisions_table).where(revisions_table.c.id == revision_id)).first()
        return dict(row._mapping) if row else None

    def list_revisions(self, quarter_id: str) -> list[dict]:
        cols = [revisions_table.c.id, revisions_table.c.saved_at, revisions_table.c.saved_by, revisions_table.c.note]
        with self.engine.connect() as c:
            rows = c.execute(select(*cols).where(revisions_table.c.quarter_id == quarter_id)
                             .order_by(revisions_table.c.id.desc()))
            return [dict(r._mapping) for r in rows]

    def list_quarters(self) -> list[dict]:
        with self.engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(select(quarters_table).order_by(quarters_table.c.quarter_id))]
