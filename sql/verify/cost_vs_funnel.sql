-- Events-table HB cost vs supply funnel, whole perimeter, EUR. Edit the window.
WITH fx AS (
  SELECT date_trunc('month', date) AS mo, rate_euros
  FROM st_datalakehouse.analytics.currency_rates_monthly WHERE currency = 'USD'
),
ev AS (
  SELECT date_trunc('month', date) AS mo,
         SUM(COALESCE(ssp_hb_net_insert_cost, 0)) / 1000 AS hb_usd
  FROM st_datalakehouse.ad_exchange.ssp_events_daily_simplified
  WHERE date BETWEEN DATE '2026-09-27' AND DATE '2026-10-26'
    AND source_type IS DISTINCT FROM 'Beachfront' AND channel_id IS DISTINCT FROM 'Beachfront'
  GROUP BY 1
)
SELECT
  (SELECT SUM(ev.hb_usd * fx.rate_euros) FROM ev JOIN fx USING (mo))  AS events_hb_cost_eur,
  SUM(hb_insert_cost_eur)                                               AS funnel_hb_line_eur,
  SUM(publisher_revenue_eur)                                            AS funnel_payout_eur
FROM st_datalakehouse.analytics.etl_ssp_supply_funnel_daily_local
WHERE date BETWEEN DATE '2026-09-27' AND DATE '2026-10-26'
  AND channel_id IS DISTINCT FROM 'Beachfront' AND source_type IS DISTINCT FROM 'Beachfront'
