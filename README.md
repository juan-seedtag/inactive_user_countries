# User countries — SSP supply health

Daily dashboard of every user country's supply funnel, split into **Active
Markets** (the fixed commercial footprint) and **Geo Expansion** (everywhere
else), drilled down to the editorial groups inside each country — and from there into
the demand side: which SSP pipes carry the traffic, which of them are 1:1 DSP
connections, and which brands those DSPs actually bid.

## The drill (left → right)

1. **Countries + editorial groups** (landing view) — supply funnel per
   country, in two sections (Active Markets, then Geo Expansion); expanding a
   row shows its top editorial groups. «SSPs →» moves right.
2. **SSP pipes** — the same funnel per channel inside the selected country (or
   editorial group). A pipe that carried exactly one DSP over the window
   (Direct or BidSwitch) **and no unattributable traffic** is displayed as that
   DSP: its requests ARE the DSP's requests. Reseller pools are terminal — the
   fan-out to individual DSPs happens inside the reseller's exchange and is not
   observable from Seedtag data. So are pipes labelled `1 DSP + unmapped`: one
   named seat plus traffic the demand table cannot attribute, where naming the
   whole pipe after that seat would overstate it. «Brands →» moves right only on
   true 1:1 pipes.
3. **Brands (adomains)** — top advertiser domains that DSP bid, with bids,
   impressions and gross revenue (USD).

**Money columns are operational, not Finance.** Revenue is Seedtag revenue from
the event stream (USD). **Pub cost is an SSP-side allocation estimate** —
impression cost + HB net insert cost — and Margin derives from it. True
publisher payout is defined per publisher, from publisher reports, and never per
user country; splitting it by the country of the user who saw the ad is
inherently a proxy. Read Pub cost and Margin as directional, and never
reconcile them against Finance's Publisher Revenue (publisher-reported, EUR,
monthly-average FX, publisher grain only).

**The 'Others' caveat.** The demand table
(`analytics.etl_ssp_responses_daily_enriched`) buckets `user_country` into 19
key markets + `'Others'` — the bucketing is a hardcoded CASE in the dbt model
`stg_ssp_responses_hourly.sql`, applied at aggregation time, so long-tail
detail is unrecoverable. Brand data is exact for countries that are
key markets (e.g. IN) and an explicitly-labeled long-tail proxy for the rest.
Adding countries to that CASE (dbt PR; precedent: de_dbt_lakehouse#743) would
make them exact from the deploy date forward.

`index.html` is regenerated every morning by GitHub Actions and committed back
to the repo. Open it directly, or serve it with GitHub Pages.

## The two sections

There is **no inactivity threshold**. Every user country with at least **1 M
requests** over the window (a trailing **30 closed days** by default, so rates
read as monthly, not one noisy week) appears, split by `ACTIVE_MARKETS` in
`scripts/update_dashboard.py`:

| Section | Membership |
|---|---|
| **Active Markets** | US, MX, BR, AR, CO, ES, FR, IT, GB, DE, NL, AE — the fixed commercial footprint |
| **Geo Expansion** | Every other user country above the request floor |

Membership is decided in the generator, not in SQL, so the sections can be
re-cut from `data/latest.json` with `--from-cache` without re-scanning the
warehouse. Status pills are informational only (No bids / Near zero / Very
low < 0.9 % / Active) and do not filter anything.

Editorial-group detail shows the **top 15** groups per country with at least
**100 K** requests.

**Beachfront is excluded from every supply scan** (`source_type` and
`channel_id` both `IS DISTINCT FROM 'Beachfront'`). Beachfront is CTV supply
sharing the same events table, and it is large: ~43.7 B requests on 2026-08-05
alone, with near-zero web bids. Leaving it in inflates per-country request
volume and drags bid rate down, misstating CTV volume as weak web demand. The
demand table already excludes it, so including it on the supply side would
compare two different perimeters.

The geo filter also requires `length(user_country) = 2` — alongside `''`,
`'undefined'` and `NULL`, this column has carried corrupted binary values in
production.

The page footer prints live bid rates for US, FR, ES, GB and DE over the same
window, so every rate on the page can be read against real reference points
rather than numbers that were true on the day the page was written. Section
membership and the floors live in `scripts/update_dashboard.py` — change them
there and both the SQL and the page follow, since the page reads its
configuration out of the embedded payload.

## Layout

```
scripts/update_dashboard.py   query -> render -> index.html
scripts/trino_client.py       Trino connection (shared Seedtag pattern, unmodified)
sql/inactive_countries.sql    phase 1: all countries above the floor (cheap, one grain)
sql/country_drill.sql         phase 2: EG + country x SSP + EG x SSP in ONE scan,
                              filtered to the phase-1 countries
sql/channel_mapping.sql       phase 3a: channel -> DSP identity
                              (1:1 vs reseller pool vs partly-unmapped)
sql/adomain_detail.sql        phase 3b: top brands per demand scope x channel
sql/benchmarks.sql            bid rate for reference markets
template/dashboard.html       page body with __PLACEHOLDER__ slots
template/dashboard_v3.html    dashboard.html + world-map graft (see index_v3)
template/world_map_paths.json Natural Earth 110m geometry, ISO2-keyed (one-time,
                              regenerate with scripts/build_world_map.py)
scripts/build_index_v3.py     cache -> index_v3.html (map + full dashboard)
data/latest.json              last successful query result (cached, committed)
index.html                    generated output (committed)
index_v3.html                 map + full dashboard, built on demand (standalone)
```

**index_v3** is the map-plus-dashboard variant: a choropleth world map
(colour by bid rate / requests / revenue / margin / a categorical demand-status
mode, hover tooltips, click a country to jump to its table row) sitting on top
of the complete dashboard — same tabs, drill-downs and footnotes as index.html,
same cached payload. On top of that it adds: per-country bid-rate sparklines
and a "what changed" strip (both fed by `data/trends.json`), request-volume
bars in the cells, a country search box that also dims the map, a zero-bid
filter (toggle button + clickable stat tile), a compact-columns toggle, sticky
tabs, table-row hover highlighting the country on the map, deep links
(`#s/ge`, `#c/PH`, `#a/PH//<pipe>/<dsp>`), and status pills computed relative
to the live benchmark median instead of hardcoded thresholds. Rebuild with:

```bash
python scripts/fetch_trends.py      # optional: refresh monthly history (Trino)
python scripts/build_index_v3.py    # cache-only, ~1s
```

`fetch_trends.py` pulls per-country monthly requests/bid-rate from
`ssp_events_monthly_simplified` (same Beachfront-excluded perimeter) into
`data/trends.json`; without that file the page renders with trend features
hidden.

It is not wired into the daily GitHub Action; promote it by pointing the
workflow (or update_dashboard.py's TEMPLATE/OUTPUT) at the v3 template once
it has proven out.

The two-phase shape is deliberate: phase 1 pays one country-grain scan to find
the ~230 countries above the floor, and everything heavier is filtered to that list,
which keeps the group-by/shuffle small. All supply drill grains share a single
scan (`country_drill.sql` UNION ALL of pre-aggregated CTEs) — never one query
per grain.

## Running it locally

One-time Google OAuth login, if you don't already have a Seedtag token:

```bash
python scripts/trino_client.py --login
```

That writes `~/.config/seedtag/token.json`. Then:

```bash
pip install -r requirements.txt
python scripts/update_dashboard.py
```

Useful variations:

```bash
python scripts/update_dashboard.py --days 14              # longer window
python scripts/update_dashboard.py --end-date 2026-08-04  # fixed end day
python scripts/update_dashboard.py --from-cache           # re-render, no Trino
```

`--from-cache` rebuilds `index.html` from `data/latest.json`, which is how to
iterate on the template without re-running a multi-minute query.

## The scheduled job

`.github/workflows/update-dashboard.yml` runs at **07:00 UTC daily** (~09:00
Madrid in summer) and can also be triggered manually from the Actions tab, where
the window length and end date are exposed as inputs.

Two secrets are required, using the same names as the other Seedtag dashboard
repos:

| Secret | Contents |
|---|---|
| `GOOGLE_TOKEN` | The full contents of your `token.json` |
| `TRINO_USER` | Your Seedtag email, e.g. `juanperez@seedtag.com` |

The job writes `token.json` from the secret, runs the generator, deletes the
token, then commits `index.html` and `data/latest.json` only if they changed.
The HTML is also uploaded as a workflow artifact on every run, successful or not.

### Things that will bite you

- **The daily table keeps only ~36 closed days.** The default 30-day window
  leaves little headroom — a few days of pipeline delay silently shortens the
  window (the page's window label always shows the real dates). A window older
  than retention returns nothing. The generator refuses to write an empty
  dashboard rather
  than silently publishing a blank table, so the previous `index.html` survives
  a bad window.
- **The window ends yesterday, not today.** `ssp_events_daily_simplified` is
  T-1; including today would render a partial day as a collapse in activity.
- **`GOOGLE_TOKEN` refresh tokens can be revoked.** If the job starts failing
  auth, re-run `--login` locally and update the secret.
- **The query is slow** (several minutes — it scans a week of the events table
  at country × editorial-group grain). The workflow allows 60 minutes.

## Serving it with GitHub Pages

Settings → Pages → deploy from branch `main`, folder `/ (root)`. The dashboard
is then at `https://<org>.github.io/<repo>/`, refreshed by each daily commit.
