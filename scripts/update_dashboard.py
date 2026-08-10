#!/usr/bin/env python3
"""Rebuild the inactive-user-countries dashboard from Trino.

Queries the SSP events daily table for user countries whose bid rate is below
the inactivity threshold, plus the editorial groups inside each of them, and
renders `index.html` from `template/dashboard.html`.

Usage:
    python scripts/update_dashboard.py                    # last 7 closed days
    python scripts/update_dashboard.py --days 14
    python scripts/update_dashboard.py --end-date 2026-08-04
    python scripts/update_dashboard.py --from-cache        # re-render, no Trino

The raw query result is cached to `data/latest.json` on every successful run so
the page can be re-rendered (template tweaks, styling) without touching the
warehouse, and so a failed run leaves the previous dashboard intact.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# --- Inactivity definition -------------------------------------------------
# A country is "inactive" when demand barely responds to its supply. 0.5% is
# deliberately just above Thailand's rate (~0.49%) and well below the healthy
# markets in benchmarks.sql, which sit at 0.7%+.
BID_RATE_THRESHOLD = 0.005
REQUEST_FLOOR = 1_000_000      # ignore countries too small to read a rate from
DETAIL_FLOOR = 100_000         # ignore editorial groups too small to matter
TOP_N_GROUPS = 15              # editorial groups shown per country
BENCHMARK_COUNTRIES = ["US", "FR", "ES", "GB", "DE"]

OUTPUT_HTML = PROJECT_ROOT / "index.html"
TEMPLATE = PROJECT_ROOT / "template" / "dashboard.html"
SQL_DIR = PROJECT_ROOT / "sql"
DATA_DIR = PROJECT_ROOT / "data"
CACHE = DATA_DIR / "latest.json"


def window(end_date: date | None, days: int) -> tuple[date, date]:
    """Return the (start, end) window, inclusive.

    Defaults to the last `days` closed days. The daily table is T-1, so the
    most recent complete day is yesterday; using today would render a partial
    day as if it were a real drop in activity.
    """
    end = end_date or (datetime.now(timezone.utc).date() - timedelta(days=1))
    return end - timedelta(days=days - 1), end


def load_sql(name: str, **params) -> str:
    return (SQL_DIR / name).read_text(encoding="utf-8").format(**params)


def fetch(start: date, end: date) -> dict:
    """Run both queries and return the payload the template expects."""
    from trino_client import run_trino_query

    user_email = os.getenv("TRINO_USER", "unknown")
    common = {
        "user_email": user_email,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }

    main_sql = load_sql(
        "inactive_countries.sql",
        bid_rate_threshold=BID_RATE_THRESHOLD,
        request_floor=REQUEST_FLOOR,
        detail_floor=DETAIL_FLOOR,
        top_n=TOP_N_GROUPS,
        **common,
    )
    print(f"Querying {start} .. {end} (threshold {BID_RATE_THRESHOLD:.3%})…", flush=True)
    rows = run_trino_query(main_sql)
    print(f"  {len(rows)} rows", flush=True)

    bench_sql = load_sql(
        "benchmarks.sql",
        benchmark_countries=", ".join(f"'{c}'" for c in BENCHMARK_COUNTRIES),
        **common,
    )
    bench = run_trino_query(bench_sql)
    print(f"  {len(bench)} benchmark rows", flush=True)

    countries = [slim(r) for r in rows if r["level"] == "country"]
    details = [slim(r) for r in rows if r["level"] == "detail"]
    if not countries:
        raise SystemExit(
            "Query returned no inactive countries — refusing to overwrite the "
            "dashboard with an empty table. Check the date window: the daily "
            "table retains roughly 36 closed days."
        )

    return {
        "meta": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "window_days": (end - start).days + 1,
            "bid_rate_threshold": BID_RATE_THRESHOLD,
            "request_floor": REQUEST_FLOOR,
            "detail_floor": DETAIL_FLOOR,
            "top_n": TOP_N_GROUPS,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "benchmarks": [
                {"c": b["user_country"], "br": num(b["bid_rate"])} for b in bench
            ],
        },
        "countries": countries,
        "details": details,
    }


def num(v):
    """Trino DECIMAL comes back as Decimal; JSON needs a float."""
    return None if v is None else float(v)


def slim(r: dict) -> dict:
    """Short keys — this payload is embedded in the page, so bytes matter."""
    return {
        "c": r["user_country"],
        "g": r.get("editorial_group_name"),
        "rq": int(r["requests"]),
        "b": int(r["bids"]),
        "w": int(r["wins"]),
        "i": int(r["impressions"]),
        "br": num(r["bid_rate"]),
        "wr": num(r["win_rate"]),
        "fr": num(r["fill_rate"]),
    }


def fmt_count(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.0f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.0f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def month_day(d: date) -> str:
    return f"{d:%b} {d.day}"


def render(payload: dict) -> str:
    meta = payload["meta"]
    start = date.fromisoformat(meta["start_date"])
    end = date.fromisoformat(meta["end_date"])
    window_label = f"{month_day(start)} – {month_day(end)}, {end:%Y}"

    benchmarks = ", ".join(
        f"{b['c']} {b['br'] * 100:.2f}%" for b in meta["benchmarks"] if b["br"] is not None
    ) or "unavailable for this window"

    substitutions = {
        "__PAYLOAD__": json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        "__WINDOW_LABEL__": window_label,
        "__WINDOW_DAYS__": str(meta["window_days"]),
        "__THRESHOLD_PCT__": f"{meta['bid_rate_threshold'] * 100:.2f}%",
        "__FLOOR_LABEL__": fmt_count(meta["request_floor"]),
        "__DETAIL_FLOOR_LABEL__": fmt_count(meta["detail_floor"]),
        "__TOP_N__": str(meta["top_n"]),
        "__BENCHMARKS__": benchmarks,
        "__GENERATED_AT__": meta["generated_at"],
    }

    html = TEMPLATE.read_text(encoding="utf-8")
    for key, value in substitutions.items():
        html = html.replace(key, value)

    leftover = [k for k in substitutions if k in html]
    if leftover:
        raise SystemExit(f"Template placeholders not substituted: {leftover}")

    # The template is a body fragment (it was authored for the Artifact
    # renderer, which supplies its own document shell). Wrap it so the file
    # also stands alone when opened directly or served from GitHub Pages.
    # <title> and <style> must be hoisted into <head> — a <title> left in
    # <body> is invalid and browsers do not reliably use it for the tab.
    head_tags, body = [], html
    for tag in ("title", "style"):
        while True:
            open_at = body.find(f"<{tag}")
            if open_at == -1:
                break
            close_at = body.index(f"</{tag}>", open_at) + len(f"</{tag}>")
            head_tags.append(body[open_at:close_at])
            body = body[:open_at] + body[close_at:]

    head = "\n".join(head_tags)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"{head}\n"
        "</head>\n"
        "<body>"
        + body.lstrip("\n")
        + "</body>\n</html>\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=7, help="window length (default 7)")
    ap.add_argument(
        "--end-date",
        type=lambda s: date.fromisoformat(s),
        help="last day of the window (default: yesterday UTC)",
    )
    ap.add_argument(
        "--from-cache",
        action="store_true",
        help="re-render from data/latest.json without querying Trino",
    )
    args = ap.parse_args()

    if args.from_cache:
        if not CACHE.exists():
            raise SystemExit(f"No cache at {CACHE} — run once without --from-cache first.")
        payload = json.loads(CACHE.read_text(encoding="utf-8"))
        print(f"Re-rendering from {CACHE} ({payload['meta']['generated_at']})")
    else:
        start, end = window(args.end_date, args.days)
        payload = fetch(start, end)
        DATA_DIR.mkdir(exist_ok=True)
        CACHE.write_text(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )

    OUTPUT_HTML.write_text(render(payload), encoding="utf-8")
    n_c = len(payload["countries"])
    n_d = len(payload["details"])
    total = sum(c["rq"] for c in payload["countries"])
    print(
        f"Wrote {OUTPUT_HTML.relative_to(PROJECT_ROOT)} — "
        f"{n_c} inactive countries, {n_d} editorial-group rows, "
        f"{fmt_count(total)} unmonetized requests"
    )


if __name__ == "__main__":
    main()
