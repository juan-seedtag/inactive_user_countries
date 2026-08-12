-- @user:{user_email} @skill:barbi
-- Phase 2: the entire supply-side drill for the inactive countries only.
-- ONE scan of the events table produces all three grains; {country_list}
-- (computed by phase 1) keeps the group-by and shuffle small.
--
--   level = 'eg'              -> top {top_n} editorial groups per country
--   level = 'country_channel' -> top {channel_top_n} SSP pipes per country
--   level = 'eg_channel'      -> top {channel_top_n} SSP pipes per (country, top EG)
WITH base AS (
    SELECT
        user_country,
        editorial_group_name,
        channel_id,
        SUM(ssp_requests)    AS requests,
        SUM(ssp_bids)        AS bids,
        SUM(ssp_wins)        AS wins,
        SUM(ssp_impressions) AS impressions,
        -- Seedtag operational revenue (USD) and publisher payout proxy (USD).
        -- Same definitions as inactive_countries.sql; insertion_cost is
        -- deliberately excluded (would double-count the HB path).
        SUM(COALESCE(seedtag_revenue,
            (ssp_net_imp_paid - COALESCE(ssp_post_auction_discount_amount, 0)
             + COALESCE(curator_margin, 0)) / 1000))    AS revenue_usd,
        SUM(ssp_impression_cost) / 1000                 AS publisher_cost_usd
    FROM st_datalakehouse.ad_exchange.ssp_events_daily_simplified
    WHERE date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
      AND user_country IN ({country_list})
    GROUP BY user_country, editorial_group_name, channel_id
),
eg AS (
    SELECT
        user_country,
        editorial_group_name,
        SUM(requests)           AS requests,
        SUM(bids)               AS bids,
        SUM(wins)               AS wins,
        SUM(impressions)        AS impressions,
        SUM(revenue_usd)        AS revenue_usd,
        SUM(publisher_cost_usd) AS publisher_cost_usd
    FROM base
    GROUP BY user_country, editorial_group_name
    HAVING SUM(requests) >= {detail_floor}
),
eg_ranked AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY user_country ORDER BY requests DESC) AS rn
    FROM eg
),
country_channel AS (
    SELECT
        user_country,
        channel_id,
        SUM(requests)           AS requests,
        SUM(bids)               AS bids,
        SUM(wins)               AS wins,
        SUM(impressions)        AS impressions,
        SUM(revenue_usd)        AS revenue_usd,
        SUM(publisher_cost_usd) AS publisher_cost_usd
    FROM base
    WHERE channel_id IS NOT NULL
    GROUP BY user_country, channel_id
    HAVING SUM(requests) >= {channel_floor}
),
cc_ranked AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY user_country ORDER BY requests DESC) AS rn
    FROM country_channel
),
eg_channel AS (
    SELECT
        b.user_country,
        b.editorial_group_name,
        b.channel_id,
        b.requests, b.bids, b.wins, b.impressions,
        b.revenue_usd, b.publisher_cost_usd,
        ROW_NUMBER() OVER (
            PARTITION BY b.user_country, b.editorial_group_name
            ORDER BY b.requests DESC
        ) AS rn
    FROM base b
    JOIN eg_ranked t
      ON  b.user_country = t.user_country
      AND b.editorial_group_name IS NOT DISTINCT FROM t.editorial_group_name
      AND t.rn <= {top_n}
    WHERE b.channel_id IS NOT NULL
      AND b.requests >= {eg_channel_floor}
)
SELECT
    'eg'                  AS level,
    user_country,
    editorial_group_name,
    CAST(NULL AS VARCHAR) AS channel_id,
    requests, bids, wins, impressions,
    revenue_usd, publisher_cost_usd
FROM eg_ranked
WHERE rn <= {top_n}
UNION ALL
SELECT
    'country_channel',
    user_country,
    CAST(NULL AS VARCHAR),
    channel_id,
    requests, bids, wins, impressions,
    revenue_usd, publisher_cost_usd
FROM cc_ranked
WHERE rn <= {channel_top_n}
UNION ALL
SELECT
    'eg_channel',
    user_country,
    editorial_group_name,
    channel_id,
    requests, bids, wins, impressions,
    revenue_usd, publisher_cost_usd
FROM eg_channel
WHERE rn <= {channel_top_n}
ORDER BY level, user_country, requests DESC
