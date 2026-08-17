#!/usr/bin/env python3
"""Fetch per-country monthly history for the dashboard sparklines.

Queries ssp_events_monthly_simplified (long retention, month grain) for the
last N complete months and writes data/trends.json:

    {"months": ["2026-02", ...],
     "countries": {"PH": {"rq": [...], "br": [...]}, ...}}

Arrays align with `months`; a month with no row for a country is null. The
Beachfront and geo filters mirror the daily scan exactly (see
sql/inactive_countries.sql) so the trend measures the same perimeter the
dashboard shows.

    python scripts/fetch_trends.py            # last 7 complete months
    python scripts/fetch_trends.py --months 12
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

OUTPUT = PROJECT_ROOT / "data" / "trends.json"

SQL = """\
-- @user:{user_email} @skill:barbi
-- Monthly per-country history for the dashboard trend sparklines.
SELECT
    date_format(date, '%Y-%m') AS ym,
    user_country,
    SUM(ssp_requests) AS requests,
    SUM(ssp_bids)     AS bids
FROM st_datalakehouse.ad_exchange.ssp_events_monthly_simplified
WHERE date >= DATE '{start_month}'
  AND date < DATE '{end_month}'
  AND source_type IS DISTINCT FROM 'Beachfront'
  AND channel_id  IS DISTINCT FROM 'Beachfront'
  AND user_country IS NOT NULL
  AND user_country NOT IN ('', 'undefined')
  AND length(user_country) = 2
GROUP BY 1, 2
HAVING SUM(ssp_requests) >= 1000000
ORDER BY 1, 2
"""


def month_add(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return date(y, m + 1, 1)


def main() -> None:
    import os

    from trino_client import run_trino_query

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--months", type=int, default=7, help="complete months to fetch")
    args = ap.parse_args()

    today = datetime.now(timezone.utc).date()
    end_month = today.replace(day=1)          # current month excluded: incomplete
    start_month = month_add(end_month, -args.months)

    sql = SQL.format(
        user_email=os.getenv("TRINO_USER", "unknown"),
        start_month=start_month.isoformat(),
        end_month=end_month.isoformat(),
    )
    print(f"Fetching {start_month:%Y-%m} .. {month_add(end_month, -1):%Y-%m}…", flush=True)
    rows = run_trino_query(sql)
    print(f"  {len(rows)} country-month rows", flush=True)
    if not rows:
        raise SystemExit("No rows — refusing to write an empty trends file.")

    months = sorted({r["ym"] for r in rows})
    idx = {m: i for i, m in enumerate(months)}
    countries: dict[str, dict] = {}
    for r in rows:
        c = countries.setdefault(
            r["user_country"],
            {"rq": [None] * len(months), "br": [None] * len(months)},
        )
        i = idx[r["ym"]]
        rq, b = int(r["requests"]), int(r["bids"])
        c["rq"][i] = rq
        c["br"][i] = round(b / rq, 6) if rq else None

    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(
        json.dumps({"months": months, "countries": countries}, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT.relative_to(PROJECT_ROOT)} — "
          f"{len(countries)} countries x {len(months)} months, "
          f"{OUTPUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
