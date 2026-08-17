#!/usr/bin/env python3
"""Render index_v3.html: the world map + the complete dashboard in one page.

Pure re-render, never queries Trino. Reads data/latest.json (written by
update_dashboard.py), template/world_map_paths.json (written by
build_world_map.py) and template/dashboard_v3.html.

    python scripts/build_index_v3.py
    python scripts/build_index_v3.py --cache data/latest.json

The v3 template is dashboard.html plus the map graft, so all 12 standard
placeholders apply; rather than duplicating the substitution logic we point
update_dashboard.render() at the v3 template and fill the one extra
placeholder (__MAP_GEO__) afterwards.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = PROJECT_ROOT / "template" / "dashboard_v3.html"
GEO = PROJECT_ROOT / "template" / "world_map_paths.json"
OUTPUT = PROJECT_ROOT / "index_v3.html"

import sys

sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
import update_dashboard as ud


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", type=Path, default=PROJECT_ROOT / "data" / "latest.json")
    args = ap.parse_args()

    if not args.cache.exists():
        raise SystemExit(f"No cache at {args.cache} — run update_dashboard.py first.")
    if not TEMPLATE.exists():
        raise SystemExit(f"No template at {TEMPLATE}.")
    if not GEO.exists():
        raise SystemExit(f"No geometry at {GEO} — run build_world_map.py first.")

    payload = json.loads(args.cache.read_text(encoding="utf-8"))

    # render() reads its module-level TEMPLATE; point it at the v3 template for
    # this process. Deliberate module-state override, documented tradeoff for
    # not duplicating the 12-key substitution block a third time.
    ud.TEMPLATE = TEMPLATE
    html = ud.render(payload)

    geo_text = GEO.read_text(encoding="utf-8").strip()
    html = html.replace("__MAP_GEO__", geo_text)

    # Monthly history for sparklines and the "what changed" strip. Optional:
    # without data/trends.json the page renders with trend features hidden.
    trends_path = PROJECT_ROOT / "data" / "trends.json"
    trends_text = trends_path.read_text(encoding="utf-8").strip() if trends_path.exists() else "null"
    if trends_text == "null":
        print("note: data/trends.json missing — run scripts/fetch_trends.py for sparklines")
    html = html.replace("__TRENDS__", trends_text)

    for ph in ("__MAP_GEO__", "__TRENDS__"):
        if ph in html:
            raise SystemExit(f"{ph} placeholder not substituted.")

    OUTPUT.write_text(html, encoding="utf-8")
    n = sum(1 for c in payload["countries"] if c.get("c"))
    print(
        f"Wrote {OUTPUT.relative_to(PROJECT_ROOT)} — {n} countries, "
        f"{OUTPUT.stat().st_size / 1024:.0f} KB"
    )


if __name__ == "__main__":
    main()
