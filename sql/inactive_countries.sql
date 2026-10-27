-- @user:{user_email} @skill:barbi
-- Phase 1: every user country with at least {request_floor} requests over the
-- window. One grain, small output — the country list feeds the phase-2 drill
-- query as a filter. The Active Market / Geo Expansion split happens in the
-- generator, not here: the SQL has no threshold, so the sections can be
-- re-cut without re-scanning. Date literals are computed by the caller, never
-- by the warehouse, so a run is reproducible from its output alone.
WITH country AS (
    SELECT
        user_country,
        SUM(ssp_requests)    AS requests,
        SUM(ssp_bids)        AS bids,
        SUM(ssp_wins)        AS wins,
        SUM(ssp_impressions) AS impressions,
        -- Seedtag operational revenue, USD. Canonical funnel formula; the
        -- COALESCE fallback mirrors etl_ssp_supply_funnel_daily_local.
        SUM(COALESCE(seedtag_revenue,
            (ssp_net_imp_paid - COALESCE(ssp_post_auction_discount_amount, 0)
             + COALESCE(curator_margin, 0)) / 1000))    AS revenue_usd,
        -- Revenue on traffic the event stream cannot cost: Tag-family source
        -- types carry revenue but neither cost field (their payout exists only
        -- in the supply funnel, per publisher). Margin is computed on the
        -- costed remainder; this slice is surfaced, never silently mixed in.
        SUM(CASE WHEN source_type IN ('Tag', 'SingleAdUnitTag', 'Amp')
                 THEN COALESCE(seedtag_revenue,
                      (ssp_net_imp_paid - COALESCE(ssp_post_auction_discount_amount, 0)
                       + COALESCE(curator_margin, 0)) / 1000)
                 ELSE 0 END)                            AS revenue_uncosted_usd,
        -- Publisher cost = the HB net insert cost ONLY (USD). ssp_impression_cost
        -- is a second valuation of the SAME payout on the same rows (99.5% of it
        -- co-occurs with HB insert cost) — summing both double-counts, which
        -- is what produced negative margins on HB-heavy countries. The HB field
        -- matches the supply funnel's HB-insert line to the euro and runs ~6%
        -- above actual payout on HB traffic. True payout exists only per
        -- publisher; per user country this is an allocation proxy — directional,
        -- never to be reconciled against Finance.
        SUM(COALESCE(ssp_hb_net_insert_cost, 0)) / 1000 AS publisher_cost_usd
    FROM st_datalakehouse.ad_exchange.ssp_events_daily_simplified
    WHERE date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
      -- Beachfront is CTV supply riding the same events table. It carries huge
      -- request volume with near-zero web bids, which both inflates per-country
      -- volume and drags bid rate under the threshold. The demand table already
      -- excludes it, so leaving it in here would measure two different
      -- perimeters against each other. IS DISTINCT FROM (not !=) keeps NULLs.
      AND source_type IS DISTINCT FROM 'Beachfront'
      AND channel_id  IS DISTINCT FROM 'Beachfront'
      -- Drop unresolvable geo: empty string, the literal 'undefined', NULL, and
      -- corrupted non-country values (binary garbage has been observed in this
      -- column) all appear here and are not real countries.
      AND user_country IS NOT NULL
      AND user_country NOT IN ('', 'undefined')
      AND length(user_country) = 2
    GROUP BY user_country
    -- Request floor only: a rate on no volume is noise, not signal.
    HAVING SUM(ssp_requests) >= {request_floor}
)
SELECT
    user_country,
    requests,
    bids,
    wins,
    impressions,
    revenue_usd,
    revenue_uncosted_usd,
    publisher_cost_usd,
    IF(requests = 0, NULL, bids * 1.0 / requests)        AS bid_rate,
    IF(bids = 0, NULL, wins * 1.0 / bids)                AS win_rate,
    IF(requests = 0, NULL, impressions * 1.0 / requests) AS fill_rate
FROM country
ORDER BY requests DESC
