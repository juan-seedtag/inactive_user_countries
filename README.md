# Inactive user countries — SSP supply health

Daily dashboard of user countries where demand barely responds to our supply,
drilled down to the editorial groups inside each country.

`index.html` is regenerated every morning by GitHub Actions and committed back
to the repo. Open it directly, or serve it with GitHub Pages.

## What "inactive" means

A user country is inactive when, over the window:

| Rule | Value | Why |
|---|---|---|
| Bid rate below | **0.5 %** | Just above Thailand (~0.49 %), well below healthy markets (0.7 %+) |
| Minimum requests | **1 M** | Below this the rate is noise, not signal |

Editorial-group detail shows the **top 15** groups per country with at least
**100 K** requests.

The page footer prints live bid rates for US, FR, ES, GB and DE over the same
window, so the threshold can always be read against real reference points
rather than numbers that were true on the day the page was written. All four
values live in `scripts/update_dashboard.py` — change them there and both the
SQL and the page follow, since the page reads its thresholds out of the
embedded payload.

## Layout

```
scripts/update_dashboard.py   query -> render -> index.html
scripts/trino_client.py       Trino connection (shared Seedtag pattern, unmodified)
sql/inactive_countries.sql    country + editorial-group grains in one result set
sql/benchmarks.sql            bid rate for reference markets
template/dashboard.html       page body with __PLACEHOLDER__ slots
data/latest.json              last successful query result (cached, committed)
index.html                    generated output (committed)
```

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

- **The daily table keeps only ~36 closed days.** A window older than that
  returns nothing. The generator refuses to write an empty dashboard rather
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
