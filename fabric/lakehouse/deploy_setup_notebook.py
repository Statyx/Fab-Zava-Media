#!/usr/bin/env python3
"""
Deploy + run NB_Setup_ZavaMedia — converts the uploaded batch CSVs (Files/raw/*.csv)
into Delta tables in the Lakehouse. The live pacing stream is NOT here (Eventhouse).

Schema is read explicitly rather than inferred: `date_key` and `month` are calendar
STRINGS ('2026-04-01', '2026-04'), and inferSchema would turn the first into a date
and leave the second a string — which silently breaks the join between fact_plan
(monthly) and fact_delivery (daily) that the whole over-delivery number rests on.
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

from pathlib import Path
from fabric._shared.helpers import load_config, load_state, save_state, get_fabric_token, print_step
from fabric.lakehouse.notebook_utils import recreate_notebook, run_notebook
from fabric.lakehouse.deploy_lakehouse import BATCH_TABLES

NOTEBOOK_NAME = "NB_Setup_ZavaMedia"

# Columns that must stay STRING even though they look numeric or date-like.
STRING_COLUMNS = ["date_key", "month", "quarter", "start_date", "end_date", "invoice_date"]


def build_notebook_py(ws_id, lh_id, lh_name):
    tables_list = ", ".join(f'"{t}"' for t in BATCH_TABLES)
    string_cols = ", ".join(f'"{c}"' for c in STRING_COLUMNS)
    return f'''# Fabric notebook source

# METADATA ********************

# META {{
# META   "kernel_info": {{
# META     "name": "synapse_pyspark"
# META   }},
# META   "dependencies": {{
# META     "lakehouse": {{
# META       "default_lakehouse": "{lh_id}",
# META       "default_lakehouse_name": "{lh_name}",
# META       "default_lakehouse_workspace_id": "{ws_id}"
# META     }}
# META   }}
# META }}

# MARKDOWN ********************

# # NB_Setup_ZavaMedia — CSV (Files/raw) -> Delta tables
#
# Calendar keys stay STRING so the monthly plan joins the daily delivery.

# CELL ********************

tables = [{tables_list}]
string_cols = [{string_cols}]
created = []

for t in tables:
    df = spark.read.csv(f"Files/raw/{{t}}.csv", header=True, inferSchema=True)
    # Force calendar keys back to string — inferSchema turns some of them into dates,
    # which breaks the plan (month) <-> delivery (date_key) join.
    for c in string_cols:
        if c in df.columns:
            df = df.withColumn(c, df[c].cast("string"))
    df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(t)
    n = df.count()
    created.append((t, n))
    print(f"{{t}}: {{n}} rows")

print("DONE", created)
'''


def main():
    cfg = load_config(); state = load_state()
    ws = state["workspace_id"]; lh = state["lakehouse_id"]; lh_name = cfg["lakehouse_name"]
    token = get_fabric_token()

    print_step(1, 3, f"Build + (re)create notebook '{NOTEBOOK_NAME}'")
    py = build_notebook_py(ws, lh, lh_name)
    nb_id = recreate_notebook(ws, NOTEBOOK_NAME, py, token)
    print(f"   notebook_id = {nb_id}")

    print_step(2, 3, "Run notebook (Spark cold start ~60-90s)")
    run_notebook(ws, nb_id, token, max_wait=900, poll_interval=20)
    print("   notebook completed")

    print_step(3, 3, "Persist state")
    state["notebook_setup_id"] = nb_id
    save_state(state)
    print("   saved notebook_setup_id")
    print(f"\nOK. {len(BATCH_TABLES)} Delta tables created. Next: deploy_eventhouse.py")


if __name__ == "__main__":
    main()
