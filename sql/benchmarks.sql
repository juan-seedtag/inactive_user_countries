-- @user:{user_email} @skill:barbi
-- Bid rate for a handful of healthy markets over the same window, so the
-- dashboard's "inactive" threshold can be read against live reference points
-- instead of numbers hardcoded on the day the page was written.
SELECT
    user_country,
    SUM(ssp_requests) AS requests,
    IF(SUM(ssp_requests) = 0, NULL,
       SUM(ssp_bids) * 1.0 / SUM(ssp_requests)) AS bid_rate
FROM st_datalakehouse.ad_exchange.ssp_events_daily_simplified
WHERE date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
  AND user_country IN ({benchmark_countries})
  -- Same perimeter as the inactive-country scan, otherwise the reference bid
  -- rates are not comparable to the numbers they are meant to calibrate.
  AND source_type IS DISTINCT FROM 'Beachfront'
  AND channel_id  IS DISTINCT FROM 'Beachfront'
GROUP BY user_country
ORDER BY bid_rate DESC
