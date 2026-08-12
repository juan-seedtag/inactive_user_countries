-- @user:{user_email} @skill:barbi
-- Channel -> demand identity, over the same window, all countries.
--
-- A channel with exactly one distinct DSP group is a 1:1 pipe (Direct or
-- BidSwitch): the channel IS the DSP, and drilling further into adomain is
-- meaningful. More than one DSP means a reseller pool — the request fan-out to
-- individual DSPs happens inside the reseller's exchange and is not observable
-- from Seedtag's data, so the SSP is the last attributable level.
--
-- Counting DSPs (rather than trusting connection_type) is deliberate: e.g. the
-- AppNexus pipe carries a Direct Xandr seat AND a reseller marketplace.
SELECT
    channel_id,
    MAX(connection_type)           AS connection_type,
    COUNT(DISTINCT dsp_group_name) AS n_dsps,
    MAX(dsp_group_name)            AS single_dsp
FROM st_datalakehouse.analytics.etl_ssp_responses_daily_enriched
WHERE date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
  AND channel_id IS NOT NULL
GROUP BY channel_id
