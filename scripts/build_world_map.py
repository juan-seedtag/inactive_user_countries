#!/usr/bin/env python3
"""One-time generator for template/world_map_paths.json.

Downloads the Natural Earth 110m admin-0 countries GeoJSON (public domain),
projects it with a plain equirectangular projection, and writes one SVG path
string per country keyed by ISO-2 code. The output is committed; rerun only
if the geometry ever needs updating.

    python scripts/build_world_map.py

No dependencies beyond the standard library.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT = PROJECT_ROOT / "template" / "world_map_paths.json"

SOURCE = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_110m_admin_0_countries.geojson"
)
# Micro-territories (SG, HK, MT…) have no polygon at 110m; this companion
# dataset carries them as points, which the page renders as small circles.
SOURCE_TINY = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_110m_admin_0_tiny_countries.geojson"
)

# Territories that appear in traffic but exist in neither 110m dataset
# (dependencies are not admin-0). Approximate centroids, (lon, lat).
SUPPLEMENT = {
    "HK": (114.17, 22.32),   # Hong Kong
    "MO": (113.55, 22.20),   # Macao
    "RE": (55.54, -21.13),   # Réunion
    "YT": (45.17, -12.83),   # Mayotte
    "GP": (-61.55, 16.27),   # Guadeloupe
    "MQ": (-61.02, 14.64),   # Martinique
    "CW": (-68.99, 12.17),   # Curaçao
    "AW": (-69.97, 12.52),   # Aruba
    "JE": (-2.13, 49.21),    # Jersey
    "GG": (-2.58, 49.46),    # Guernsey
    "GI": (-5.35, 36.14),    # Gibraltar
    "BM": (-64.75, 32.31),   # Bermuda
    "GU": (144.79, 13.44),   # Guam
    "PF": (-149.57, -17.68), # Fr. Polynesia (Tahiti)
    "NC": (165.62, -21.30),  # New Caledonia
    "VI": (-64.90, 18.34),   # US Virgin Is.
}

# viewBox is 960 x 480 (equirectangular is 2:1). Antarctica is dropped — it
# eats a fifth of the vertical space and can never carry ad traffic.
W, H = 960.0, 480.0
PRECISION = 1  # decimal places; 0.1 SVG-unit resolution keeps the file small


def project(lon: float, lat: float) -> tuple[float, float]:
    return (lon + 180.0) / 360.0 * W, (90.0 - lat) / 180.0 * H


def ring_to_path(ring: list[list[float]]) -> str:
    pts, last = [], None
    for lon, lat in ring:
        x, y = project(lon, lat)
        p = (round(x, PRECISION), round(y, PRECISION))
        if p != last:
            pts.append(p)
            last = p
    if len(pts) < 3:
        return ""
    d = f"M{pts[0][0]} {pts[0][1]}"
    d += "".join(f"L{x} {y}" for x, y in pts[1:])
    return d + "Z"


def iso2(props: dict) -> str | None:
    # ISO_A2 is '-99' for a handful of countries (France, Norway…);
    # ISO_A2_EH carries the everyday code there.
    for key in ("ISO_A2_EH", "ISO_A2"):
        v = props.get(key)
        if v and len(v) == 2 and v != "-9":
            return v.upper()
    return None


def main() -> None:
    print(f"Downloading {SOURCE} …", flush=True)
    with urllib.request.urlopen(SOURCE) as resp:
        geo = json.load(resp)

    paths: dict[str, str] = {}
    skipped = []
    for feat in geo["features"]:
        code = iso2(feat.get("properties", {}))
        if code is None:
            skipped.append(feat.get("properties", {}).get("NAME", "?"))
            continue
        if code == "AQ":
            continue
        geom = feat["geometry"]
        polys = (
            geom["coordinates"]
            if geom["type"] == "MultiPolygon"
            else [geom["coordinates"]]
        )
        d = "".join(
            ring_to_path(ring) for poly in polys for ring in poly
        )
        if d:
            # A few codes appear twice (e.g. dependencies) — keep the longer
            # (more detailed) geometry.
            if code not in paths or len(d) > len(paths[code]):
                paths[code] = d

    print(f"Downloading {SOURCE_TINY} …", flush=True)
    with urllib.request.urlopen(SOURCE_TINY) as resp:
        tiny = json.load(resp)
    points: dict[str, list[float]] = {}
    for feat in tiny["features"]:
        code = iso2(feat.get("properties", {}))
        if code is None or code in paths:
            continue
        lon, lat = feat["geometry"]["coordinates"][:2]
        x, y = project(lon, lat)
        points[code] = [round(x, PRECISION), round(y, PRECISION)]
    for code, (lon, lat) in SUPPLEMENT.items():
        if code not in paths and code not in points:
            x, y = project(lon, lat)
            points[code] = [round(x, PRECISION), round(y, PRECISION)]

    OUT.write_text(
        json.dumps(
            {"paths": paths, "points": points},
            separators=(",", ":"),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    size_kb = OUT.stat().st_size / 1024
    print(f"Wrote {OUT.relative_to(PROJECT_ROOT)} — "
          f"{len(paths)} polygon countries + {len(points)} point countries, "
          f"{size_kb:.0f} KB")
    if skipped:
        print(f"Skipped (no ISO-2): {', '.join(skipped)}", file=sys.stderr)


if __name__ == "__main__":
    main()
