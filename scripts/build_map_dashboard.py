#!/usr/bin/env python3
"""Render the standalone map test page (map.html) from cached data.

Pure re-render: reads data/latest.json (written by update_dashboard.py),
template/world_map_paths.json (written by build_world_map.py) and
template/map_dashboard.html — never queries Trino.

    python scripts/build_map_dashboard.py
    python scripts/build_map_dashboard.py --cache data/latest.json
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = PROJECT_ROOT / "template" / "map_dashboard.html"
GEO = PROJECT_ROOT / "template" / "world_map_paths.json"
MAIN_TEMPLATE = PROJECT_ROOT / "template" / "dashboard.html"
OUTPUT = PROJECT_ROOT / "map.html"


def month_day(d: date) -> str:
    return f"{d:%b} {d.day}"


def names_literal() -> str:
    """Reuse the NAMES country-name dict from the main dashboard template
    rather than maintaining a second copy."""
    m = re.search(r"const NAMES = (\{.*?\});", MAIN_TEMPLATE.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit(f"Could not find the NAMES dict in {MAIN_TEMPLATE}")
    return m.group(1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", type=Path, default=PROJECT_ROOT / "data" / "latest.json")
    args = ap.parse_args()

    if not args.cache.exists():
        raise SystemExit(f"No cache at {args.cache} — run update_dashboard.py first.")
    if not GEO.exists():
        raise SystemExit(f"No geometry at {GEO} — run build_world_map.py first.")

    payload = json.loads(args.cache.read_text(encoding="utf-8"))
    meta = payload["meta"]
    # The map only needs country-level rows and a slice of meta — dropping the
    # EG/channel/brand drill keeps the page a fraction of index.html's size.
    slim = {
        "meta": {
            "start_date": meta["start_date"],
            "end_date": meta["end_date"],
            "window_days": meta["window_days"],
            "active_markets": meta.get("active_markets"),
            "request_floor": meta["request_floor"],
        },
        "countries": [c for c in payload["countries"] if c.get("g") is None],
    }

    start = date.fromisoformat(meta["start_date"])
    end = date.fromisoformat(meta["end_date"])
    window_label = (
        f"{month_day(start)} – {month_day(end)}, {end:%Y} "
        f"(last {meta['window_days']} closed days)"
    )

    substitutions = {
        "__PAYLOAD__": json.dumps(slim, separators=(",", ":"), ensure_ascii=False),
        "__MAP_GEO__": GEO.read_text(encoding="utf-8"),
        "__NAMES__": names_literal(),
        "__WINDOW_LABEL__": window_label,
        "__GENERATED_AT__": meta["generated_at"],
    }

    html = TEMPLATE.read_text(encoding="utf-8")
    for key, value in substitutions.items():
        html = html.replace(key, value)
    leftover = [k for k in substitutions if k in html]
    if leftover:
        raise SystemExit(f"Template placeholders not substituted: {leftover}")

    # Same standalone-document wrapping as update_dashboard.render().
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
    OUTPUT.write_text(
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"{head}\n"
        "</head>\n"
        "<body>"
        + body.lstrip("\n")
        + "</body>\n</html>\n",
        encoding="utf-8",
    )
    n = len(slim["countries"])
    print(f"Wrote {OUTPUT.relative_to(PROJECT_ROOT)} — {n} countries, "
          f"{OUTPUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
