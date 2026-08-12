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
        -- Publisher cost: an operational SSP-side ESTIMATE in USD (impression
        -- cost + HB net insert cost). Both paths compensate publishers and the
        -- supply funnel books them as separate lines, so both belong here.
        -- True payout is only ever defined per publisher, from publisher
        -- reports — never per user country. Splitting it by the country of the
        -- user who saw the ad is inherently an allocation proxy, so treat this
        -- as directional and never reconcile it against Finance.
        SUM(ssp_impression_cost + COALESCE(ssp_hb_net_insert_cost, 0)) / 1000
                                                        AS publisher_cost_usd
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
