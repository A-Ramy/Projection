"""Print the data report for the live sheet (aggregates only; never names, phones or links).

    uv run python scripts/profile.py            # print to the terminal
    uv run python scripts/profile.py --save     # also write .data/data-report.md (gitignored)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from projection.config import DATA_DIR, load_secrets  # noqa: E402
from projection.data.load import load_dataset  # noqa: E402
from projection.data.report import to_markdown  # noqa: E402
from projection.storage import Store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--save", action="store_true", help="write .data/data-report.md")
    args = ap.parse_args()

    secrets = load_secrets()
    if not secrets.has_sheet_access:
        print("No service account configured. Set GOOGLE_SERVICE_ACCOUNT_JSON_B64 (see README).", file=sys.stderr)
        return 2
    settings = Store(secrets.database_url).get_settings()
    report = to_markdown(load_dataset(secrets, settings), settings)
    print(report)
    if args.save:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "data-report.md").write_text(report, encoding="utf-8")
        print(f"Saved to {DATA_DIR / 'data-report.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
