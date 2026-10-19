from projection.config import DEFAULT_SETTINGS
from projection.storage import Store, normalize_url


def test_settings_default_and_override(tmp_path):
    s = Store(f"sqlite:///{tmp_path / 't.db'}")
    assert s.get_settings()["start_date"] == DEFAULT_SETTINGS["start_date"]
    s.set_setting("scale_cap", 2.0, by="owner")
    s.set_setting("scale_cap", 1.75, by="owner")
    got = s.get_settings()
    assert got["scale_cap"] == 1.75 and got["low_conf_min_leads"] == 30


def test_revisions_are_append_only_history(tmp_path):
    s = Store(f"sqlite:///{tmp_path / 't.db'}")
    first = s.save_revision("2026-Q4", {"marketing": [{"source": "PPC NW RDS", "p_cost": 120000}]}, by="a")
    second = s.save_revision("2026-Q4", {"marketing": [{"source": "PPC NW RDS", "p_cost": 125000}]}, by="b")
    assert second > first
    assert s.latest_revision("2026-Q4")["payload"]["marketing"][0]["p_cost"] == 125000
    assert s.get_revision(first)["payload"]["marketing"][0]["p_cost"] == 120000
    assert [r["saved_by"] for r in s.list_revisions("2026-Q4")] == ["b", "a"]
    assert [q["quarter_id"] for q in s.list_quarters()] == ["2026-Q4"]
    assert s.latest_revision("2027-Q1") is None


def test_neon_url_uses_psycopg_driver():
    assert normalize_url("postgresql://u:p@host/db").startswith("postgresql+psycopg://")
    assert normalize_url("postgres://u:p@host/db").startswith("postgresql+psycopg://")


def test_export_has_settings_and_every_version(tmp_path):
    import json

    from projection.storage import Store

    store = Store(f"sqlite:///{tmp_path / 'b.db'}")
    store.set_setting("scale_cap", 2.0, by="owner")
    store.save_revision("2026-Q4", {"quarter_id": "2026-Q4"}, by="owner", note="a")
    store.save_revision("2026-Q4", {"quarter_id": "2026-Q4"}, by="owner", note="b")
    out = json.loads(json.dumps(store.export()))
    assert out["settings"] == {"scale_cap": 2.0} and [r["note"] for r in out["projection_revisions"]] == ["a", "b"]
