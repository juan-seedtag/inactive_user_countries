-- @user:{user_email} @skill:barbi
-- Inactive user countries and their editorial groups.
--
-- Returns two grains in one result set, distinguished by `level`:
--   level = 'country' -> one row per inactive user country
--   level = 'detail'  -> top {top_n} editorial groups within each of those countries
--
-- "Inactive" = bid rate below {bid_rate_threshold} on at least {request_floor}
-- requests over the window. Date literals are computed by the caller, never by
-- the warehouse, so a run is reproducible from its output alone.
WITH base AS (
    SELECT
        user_country,
        editorial_group_name,
        SUM(ssp_requests)    AS requests,
        SUM(ssp_bids)        AS bids,
        SUM(ssp_wins)        AS wins,
        SUM(ssp_impressions) AS impressions
    FROM st_datalakehouse.ad_exchange.ssp_events_daily_simplified
    WHERE date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
      -- Drop unresolvable geo: empty string, the literal 'undefined', and NULL
      -- all appear in this column and are not real countries.
      AND user_country IS NOT NULL
      AND user_country NOT IN ('', 'undefined')
    GROUP BY user_country, editorial_group_name
),
country AS (
    SELECT
        user_country,
        SUM(requests)    AS requests,
        SUM(bids)        AS bids,
        SUM(wins)        AS wins,
        SUM(impressions) AS impressions
    FROM base
    GROUP BY user_country
    HAVING SUM(requests) >= {request_floor}
       AND SUM(bids) * 1.0 / SUM(requests) < {bid_rate_threshold}
),
detail AS (
    SELECT
        b.*,
        ROW_NUMBER() OVER (PARTITION BY b.user_country ORDER BY b.requests DESC) AS rn
    FROM base b
    JOIN country c ON b.user_country = c.user_country
    WHERE b.requests >= {detail_floor}
)
SELECT
    'country'                  AS level,
    user_country,
    CAST(NULL AS VARCHAR)      AS editorial_group_name,
    requests,
    bids,
    wins,
    impressions,
    IF(requests = 0, NULL, bids * 1.0 / requests)        AS bid_rate,
    IF(bids = 0, NULL, wins * 1.0 / bids)                AS win_rate,
    IF(requests = 0, NULL, impressions * 1.0 / requests) AS fill_rate
FROM country
UNION ALL
SELECT
    'detail',
    user_country,
    editorial_group_name,
    requests,
    bids,
    wins,
    impressions,
    IF(requests = 0, NULL, bids * 1.0 / requests),
    IF(bids = 0, NULL, wins * 1.0 / bids),
    IF(requests = 0, NULL, impressions * 1.0 / requests)
FROM detail
WHERE rn <= {top_n}
ORDER BY level, requests DESC
