-- Share of impression cost on rows that ALSO carry HB insert cost. Expect ~0.995.
SELECT
  SUM(CASE WHEN ssp_impression_cost > 0 AND COALESCE(ssp_hb_net_insert_cost,0) > 0
           THEN ssp_impression_cost ELSE 0 END) / SUM(ssp_impression_cost)
    AS share_of_imp_cost_on_rows_that_also_have_hb_cost
FROM st_datalakehouse.ad_exchange.ssp_events_daily_simplified
WHERE date BETWEEN DATE '2026-10-13' AND DATE '2026-10-19'
  AND source_type IS DISTINCT FROM 'Beachfront' AND channel_id IS DISTINCT FROM 'Beachfront'
