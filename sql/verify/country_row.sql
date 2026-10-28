-- Recompute one dashboard country row. Edit the window and country.
SELECT
    SUM(ssp_requests)    AS requests,
    SUM(ssp_bids)        AS bids,
    SUM(ssp_wins)        AS wins,
    SUM(ssp_impressions) AS impressions,
    SUM(COALESCE(seedtag_revenue,
        (ssp_net_imp_paid - COALESCE(ssp_post_auction_discount_amount, 0)
         + COALESCE(curator_margin, 0)) / 1000))                        AS revenue_usd,
    SUM(CASE WHEN source_type IN ('Tag', 'SingleAdUnitTag', 'Amp')
             THEN COALESCE(seedtag_revenue,
                  (ssp_net_imp_paid - COALESCE(ssp_post_auction_discount_amount, 0)
                   + COALESCE(curator_margin, 0)) / 1000) ELSE 0 END)  AS uncosted_usd,
    SUM(COALESCE(ssp_hb_net_insert_cost, 0)) / 1000                     AS pub_cost_usd
FROM st_datalakehouse.ad_exchange.ssp_events_daily_simplified
WHERE date BETWEEN DATE '2026-09-27' AND DATE '2026-10-26'
  AND user_country = 'AU'
  -- AND editorial_group_name = 'theguardian'   -- for an expanded EG row
  AND source_type IS DISTINCT FROM 'Beachfront'
  AND channel_id  IS DISTINCT FROM 'Beachfront'
