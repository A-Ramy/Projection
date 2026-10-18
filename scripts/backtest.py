"""Backtest a finished quarter against the live sheet (aggregates only; prints, never saves).

    uv run python scripts/backtest.py                 # Q3 2026 from Q1–Q2
    uv run python scripts/backtest.py 2026-Q2 last_quarter
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from projection.backtest import METRICS, backtest  # noqa: E402
from projection.config import load_secrets  # noqa: E402
from projection.data.load import load_dataset  # noqa: E402
from projection.periods import parse_period_key  # noqa: E402
from projection.storage import Store  # noqa: E402


def main() -> int:
    target = parse_period_key(sys.argv[1] if len(sys.argv) > 1 else "2026-Q3")
    lookback = sys.argv[2] if len(sys.argv) > 2 else "last_2_quarters"
    secrets = load_secrets()
    if not secrets.has_sheet_access:
        print("No service account configured.", file=sys.stderr)
        return 2
    settings = Store(secrets.database_url).get_settings()
    bt = backtest(load_dataset(secrets, settings), target, settings, lookback)
    print(f"Backtest {target.label} using {bt.window_label}")
    print(f"{'source':28}" + "".join(f"{m + ' pred':>16}{m + ' actual':>16}{'err':>8}" for m in METRICS))
    for r in bt.rows:
        if not r.predictable:
            print(f"{r.source:28}{r.note}")
            continue
        cells = ""
        for m in METRICS:
            p, a, e = getattr(r, f"pred_{m}"), getattr(r, f"actual_{m}"), r.error(m)
            cells += f"{p:16,.1f}{a:16,.1f}{(f'{e:+.0%}' if e is not None else '—'):>8}"
        print(f"{r.source:28}{cells}")
    print("MAPE " + ", ".join(f"{m} {bt.mape(m):.0%}" if bt.mape(m) is not None else f"{m} —" for m in METRICS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
