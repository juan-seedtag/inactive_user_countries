# Manual verification queries (run in your Trino client)

Fill in the window from the dashboard footer and the country / editorial group
you want to check. All three use the dashboard's perimeter (Beachfront excluded).

1. `country_row.sql` — recompute one country row from scratch; every column must
   match the page to the cent. Margin = (revenue − uncosted − pub_cost) / (revenue − uncosted).
2. `cost_vs_funnel.sql` — events-table HB cost vs the supply funnel, in EUR.
   OK = events ≈ funnel HB line (±0.1%) and events / payout ≈ 0.87 (the rest is
   Tag-family payout the event stream cannot see).
3. `double_count_test.sql` — share of impression cost sitting on rows that also
   carry HB insert cost. OK ≈ 0.995: the two fields are the same payout valued
   twice and must never be summed (the Aug–Oct 2026 bug).
