-- @user:{user_email} @skill:barbi
-- Phase 4: calendar-month totals per country for exactly three partitions —
-- the last complete month M, M-1 (MoM) and M-12 (YoY) — from the monthly
-- rollup, which keeps long history (the daily table retains ~36 days).
-- Same perimeter and money definitions as inactive_countries.sql. No request
-- floor: a prior month must be present even when small, or the delta reads
-- as "new" instead of a number. {months} is a list of first-of-month DATE
-- literals computed by the caller.
SELECT
    date_format(date, '%Y-%m')  AS ym,
    user_country,
    SUM(ssp_requests)           AS requests,
    SUM(ssp_bids)               AS bids,
    SUM(ssp_wins)               AS wins,
    SUM(ssp_impressions)        AS impressions,
    SUM(COALESCE(seedtag_revenue,
        (ssp_net_imp_paid - COALESCE(ssp_post_auction_discount_amount, 0)
         + COALESCE(curator_margin, 0)) / 1000))        AS revenue_usd,
    SUM(CASE WHEN source_type IN ('Tag', 'SingleAdUnitTag', 'Amp')
             THEN COALESCE(seedtag_revenue,
                  (ssp_net_imp_paid - COALESCE(ssp_post_auction_discount_amount, 0)
                   + COALESCE(curator_margin, 0)) / 1000)
             ELSE 0 END)                                AS revenue_uncosted_usd,
    SUM(COALESCE(ssp_hb_net_insert_cost, 0)) / 1000     AS publisher_cost_usd
FROM st_datalakehouse.ad_exchange.ssp_events_monthly_simplified
WHERE date IN ({months})
  AND user_country IN ({country_list})
  AND source_type IS DISTINCT FROM 'Beachfront'
  AND channel_id  IS DISTINCT FROM 'Beachfront'
  AND user_country IS NOT NULL
  AND user_country NOT IN ('', 'undefined')
  AND length(user_country) = 2
GROUP BY 1, 2
ORDER BY 1, 2
