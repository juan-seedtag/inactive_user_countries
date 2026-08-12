-- @user:{user_email} @skill:barbi
-- Phase 1: identify the inactive user countries. One grain, small output —
-- the country list feeds the phase-2 drill query as a filter.
--
-- "Inactive" = bid rate below {bid_rate_threshold} on at least {request_floor}
-- requests over the window. Date literals are computed by the caller, never by
-- the warehouse, so a run is reproducible from its output alone.
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
        -- Publisher payout (operational proxy, USD, raw x1000). Do NOT add
        -- ssp_insertion_cost: same underlying field on the HB insertion event,
        -- summing both double-counts the HB path.
        SUM(ssp_impression_cost) / 1000                 AS publisher_cost_usd
    FROM st_datalakehouse.ad_exchange.ssp_events_daily_simplified
    WHERE date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
      -- Drop unresolvable geo: empty string, the literal 'undefined', and NULL
      -- all appear in this column and are not real countries.
      AND user_country IS NOT NULL
      AND user_country NOT IN ('', 'undefined')
    GROUP BY user_country
    HAVING SUM(ssp_requests) >= {request_floor}
       AND SUM(ssp_bids) * 1.0 / SUM(ssp_requests) < {bid_rate_threshold}
)
SELECT
    user_country,
    requests,
    bids,
    wins,
    impressions,
    revenue_usd,
    publisher_cost_usd,
    IF(requests = 0, NULL, bids * 1.0 / requests)        AS bid_rate,
    IF(bids = 0, NULL, wins * 1.0 / bids)                AS win_rate,
    IF(requests = 0, NULL, impressions * 1.0 / requests) AS fill_rate
FROM country
ORDER BY requests DESC
