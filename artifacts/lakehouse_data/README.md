# `artifacts/lakehouse_data/` — the demo dataset

11 CSVs, regenerated deterministically (seed 42) by
`python -m design.notebooks.generate_data`, uploaded to the lakehouse by
`python -m fabric.lakehouse.deploy_lakehouse`, then converted to Delta tables by
`deploy_setup_notebook`.

| File | Rows | Kind |
|---|---|---|
| `dim_advertiser.csv` | 5 | dimension |
| `dim_brand.csv` | 10 | dimension |
| `dim_market.csv` | 5 | dimension |
| `dim_channel.csv` | 7 | dimension |
| `dim_media_owner.csv` | 6 | dimension |
| `dim_campaign.csv` | 80 | dimension |
| `dim_date.csv` | 365 | dimension |
| `fact_plan.csv` | 720 | fact |
| `fact_delivery.csv` | 21 960 | fact |
| `fact_billing.csv` | 657 | fact |
| `pacing_events.csv` | 20 160 | streamed into the eventhouse, not the lakehouse |

`pacing_events.csv` is the odd one out: it is ingested into the KQL table by
`fabric.realtime.preload_pacing`, because the ontology binds one TimeSeries to
real-time data rather than to Delta.

**Do not edit these by hand.** They are generated output; the generator is the source
of truth, and `tests/test_smoke.py` asserts both the row counts above and the exact
delivered-vs-planned anomalies the demo turns on.
