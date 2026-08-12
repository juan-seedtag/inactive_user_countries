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

# --- Demand drill (SSP -> DSP -> brand) --------------------------------------
CHANNEL_FLOOR = 100_000        # min requests for a channel row at country grain
EG_CHANNEL_FLOOR = 50_000      # min requests for a channel row at EG grain
CHANNEL_TOP_N = 10             # channels shown per country / per EG
ADOMAIN_TOP_N = 10             # brands shown per (demand scope, channel)
# The demand table (etl_ssp_responses_daily_enriched) groups user_country into
# these key markets; every other country lands in the shared 'Others' bucket.
# Inactive countries outside this list get brand data from 'Others' as an
# explicitly-labeled proxy.
DEMAND_KEY_MARKETS = [
    "AE", "AR", "AU", "BE", "BR", "CA", "CO", "DE", "ES", "FR",
    "GB", "IN", "IT", "MX", "NL", "PL", "PT", "US", "ZA",
]

OUTPUT_HTML = PROJECT_ROOT / "index.html"
TEMPLATE = PROJECT_ROOT / "template" / "dashboard.html"
SQL_DIR = PROJECT_ROOT / "sql"
DATA_DIR = PROJECT_ROOT / "data"
CACHE = DATA_DIR / "latest.json"


def window(end_date: date | None, days: int) -> tuple[date, date]:
    """Return the (start, end) window, inclusive.

    Defaults to the last `days` days ending at the newest partition that
    actually exists in the events table. "T-1" is nominal: the yesterday
    partition can land at any hour of today, so anchoring to the calendar
    would silently produce a window whose last day has no data (observed
    2026-08-11: the Aug 10 partition was still absent at 06:49 UTC and the
    dashboard claimed a 7-day window that contained 6 days).
    """
    if end_date is None:
        from trino_client import run_trino_query

        rows = run_trino_query(
            "SELECT CAST(MAX(date) AS DATE) AS last_day "
            "FROM st_datalakehouse.ad_exchange.ssp_events_daily_simplified"
        )
        end = rows[0]["last_day"]
        if isinstance(end, str):
            end = date.fromisoformat(end)
        yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
        if end > yesterday:
            end = yesterday  # never include a live, partial day
        print(f"Newest complete partition: {end}", flush=True)
    else:
        end = end_date
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

    # Phase 1 — identify inactive countries (cheap output, one grain).
    main_sql = load_sql(
        "inactive_countries.sql",
        bid_rate_threshold=BID_RATE_THRESHOLD,
        request_floor=REQUEST_FLOOR,
        **common,
    )
    print(f"Phase 1: inactive countries {start} .. {end} "
          f"(threshold {BID_RATE_THRESHOLD:.3%})…", flush=True)
    rows = run_trino_query(main_sql)
    print(f"  {len(rows)} inactive countries", flush=True)

    countries = [slim(r) for r in rows]
    if not countries:
        raise SystemExit(
            "Query returned no inactive countries — refusing to overwrite the "
            "dashboard with an empty table. Check the date window: the daily "
            "table retains roughly 36 closed days."
        )
    inactive = [c["c"] for c in countries]

    # Phase 2 — the entire supply drill (EG, country x SSP, EG x SSP) in ONE
    # scan, filtered to the inactive countries from phase 1.
    drill_sql = load_sql(
        "country_drill.sql",
        country_list=", ".join(f"'{c}'" for c in inactive),
        detail_floor=DETAIL_FLOOR,
        top_n=TOP_N_GROUPS,
        channel_floor=CHANNEL_FLOOR,
        eg_channel_floor=EG_CHANNEL_FLOOR,
        channel_top_n=CHANNEL_TOP_N,
        **common,
    )
    print("Phase 2: EG + SSP drill inside those countries…", flush=True)
    drill_rows = run_trino_query(drill_sql)
    details = [slim(r) for r in drill_rows if r["level"] == "eg"]
    channel_rows = [r for r in drill_rows if r["level"] != "eg"]
    print(f"  {len(details)} EG rows, {len(channel_rows)} channel rows", flush=True)

    # Phase 3a — channel -> DSP identity (1:1 pipe vs reseller pool).
    print("Phase 3: channel -> DSP mapping…", flush=True)
    mapping = run_trino_query(load_sql("channel_mapping.sql", **common))
    print(f"  {len(mapping)} channels mapped", flush=True)

    # Phase 3b — brands per demand scope. Exact for inactive countries that are
    # key markets; 'Others' is the shared proxy for every long-tail country.
    scopes = sorted(
        {c if c in DEMAND_KEY_MARKETS else "Others" for c in inactive}
    )
    adomain_sql = load_sql(
        "adomain_detail.sql",
        demand_scopes=", ".join(f"'{s}'" for s in scopes),
        adomain_top_n=ADOMAIN_TOP_N,
        **common,
    )
    print(f"  top brands for demand scopes {scopes}…", flush=True)
    adomain_rows = run_trino_query(adomain_sql)
    print(f"  {len(adomain_rows)} brand rows", flush=True)

    bench_sql = load_sql(
        "benchmarks.sql",
        benchmark_countries=", ".join(f"'{c}'" for c in BENCHMARK_COUNTRIES),
        **common,
    )
    bench = run_trino_query(bench_sql)
    print(f"  {len(bench)} benchmark rows", flush=True)

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
            "channel_floor": CHANNEL_FLOOR,
            "eg_channel_floor": EG_CHANNEL_FLOOR,
            "channel_top_n": CHANNEL_TOP_N,
            "adomain_top_n": ADOMAIN_TOP_N,
            "key_markets": DEMAND_KEY_MARKETS,
        },
        "countries": countries,
        "details": details,
        "channels": [slim_channel(r) for r in channel_rows],
        # A pipe is 1:1 only when it carried exactly one named DSP AND no
        # unmapped traffic. One named DSP alongside NULL-DSP rows is a mixed
        # pipe: naming it after that DSP would attribute the whole pipe's
        # requests — and its brands — to a seat that only carried part of it.
        "chmap": {
            m["channel_id"]: {
                "ct": m["connection_type"],
                "n": int(m["n_dsps"]),
                "u": bool(m["has_unmapped"]),
                "dsp": m["single_dsp"]
                if int(m["n_dsps"]) == 1 and not m["has_unmapped"]
                else None,
            }
            for m in mapping
        },
        "adomains": [slim_adomain(r) for r in adomain_rows],
    }


def num(v):
    """Trino DECIMAL comes back as Decimal; JSON needs a float."""
    return None if v is None else float(v)


def slim(r: dict) -> dict:
    """Short keys — this payload is embedded in the page, so bytes matter.

    Rates come from the SQL when present (phase 1); drill grains carry raw
    counts only, so they are derived here.
    """
    rq, b = int(r["requests"]), int(r["bids"])
    w, i = int(r["wins"]), int(r["impressions"])
    return {
        "c": r["user_country"],
        "g": r.get("editorial_group_name"),
        "rq": rq,
        "b": b,
        "w": w,
        "i": i,
        "br": num(r["bid_rate"]) if "bid_rate" in r else (b / rq if rq else None),
        "wr": num(r["win_rate"]) if "win_rate" in r else (w / b if b else None),
        "fr": num(r["fill_rate"]) if "fill_rate" in r else (i / rq if rq else None),
        "rv": num(r.get("revenue_usd")),
        "pc": num(r.get("publisher_cost_usd")),
    }


def slim_channel(r: dict) -> dict:
    """Channel row: country (+ EG for 'detail' level) x SSP pipe, supply funnel."""
    return {
        "c": r["user_country"],
        "g": r.get("editorial_group_name"),
        "ch": r["channel_id"],
        "rq": int(r["requests"]),
        "b": int(r["bids"]),
        "w": int(r["wins"]),
        "i": int(r["impressions"]),
        "rv": num(r.get("revenue_usd")),
        "pc": num(r.get("publisher_cost_usd")),
    }


def slim_adomain(r: dict) -> dict:
    """Brand row: demand scope (key market or 'Others') x channel x adomain."""
    return {
        "s": r["user_country"],
        "ch": r["channel_id"],
        "a": r["adomain"],
        "b": int(r["bids"]),
        "i": int(r["impressions"]),
        "rv": num(r["revenue_usd"]),
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
        "__CHANNEL_FLOOR_LABEL__": fmt_count(meta.get("channel_floor", CHANNEL_FLOOR)),
        "__CHANNEL_TOP_N__": str(meta.get("channel_top_n", CHANNEL_TOP_N)),
        "__ADOMAIN_TOP_N__": str(meta.get("adomain_top_n", ADOMAIN_TOP_N)),
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
