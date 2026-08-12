-- @user:{user_email} @skill:barbi
-- Top advertiser domains (brands) per demand scope and channel.
--
-- The demand table groups user_country into key markets + 'Others'. Inactive
-- countries that are key markets (e.g. IN) get exact rows; every long-tail
-- country maps to the shared 'Others' bucket, which the dashboard presents as
-- an explicitly-labeled proxy. {demand_scopes} is the deduplicated list of
-- those scope values, computed by the caller from the inactive-country list.
WITH d AS (
    SELECT
        user_country,
        channel_id,
        adomain,
        SUM(total_response_bids) AS bids,
        SUM(total_impressions)   AS impressions,
        SUM(seedtag_revenue)     AS revenue_usd
    FROM st_datalakehouse.analytics.etl_ssp_responses_daily_enriched
    WHERE date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
      AND user_country IN ({demand_scopes})
      AND channel_id IS NOT NULL
      AND adomain IS NOT NULL AND adomain <> ''
    GROUP BY user_country, channel_id, adomain
)
SELECT user_country, channel_id, adomain, bids, impressions, revenue_usd
FROM (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY user_country, channel_id
               ORDER BY bids DESC
           ) AS rn
    FROM d
)
WHERE rn <= {adomain_top_n}
ORDER BY user_country, channel_id, bids DESC
