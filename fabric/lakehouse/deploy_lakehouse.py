#!/usr/bin/env python3
"""
Deploy the Zava Media Lakehouse: create the item + upload the batch CSVs to
OneLake Files/raw/. Delta tables are created afterwards by deploy_setup_notebook.py.

Only BATCH tables go here (dim_* and fact_*). The live pacing stream
(pacing_events) goes to the Eventhouse — see deploy_eventhouse.py.

OneLake upload uses a single reusable http.client.HTTPSConnection (3-step DFS:
PUT create -> PATCH append -> PATCH flush) — requests/urllib3 hang on OneLake DFS.
"""
import os, sys, http.client
from fabric._shared.platform_env import bootstrap
bootstrap()

from pathlib import Path
import requests
from fabric._shared.helpers import (load_config, load_state, save_state, get_fabric_token,
                     get_storage_token, fabric_headers, poll_operation,
                     find_item, print_step)
from fabric._shared.paths import ARTIFACTS as RAW

# The batch star schema. Single source of truth — deploy_setup_notebook.py imports
# this list so the Delta tables it creates can never drift from what was uploaded.
BATCH_TABLES = [
    "dim_advertiser", "dim_brand", "dim_campaign", "dim_channel",
    "dim_date", "dim_market", "dim_media_owner",
    "fact_plan", "fact_delivery", "fact_billing",
]

ONELAKE_HOST = "onelake.dfs.fabric.microsoft.com"


def upload_files(ws_id, lh_id, token):
    conn = http.client.HTTPSConnection(ONELAKE_HOST, timeout=180)
    hdr = {"Authorization": f"Bearer {token}"}
    try:
        for name in BATCH_TABLES:
            path = RAW / f"{name}.csv"
            if not path.exists():
                raise FileNotFoundError(
                    f"{path} missing — run `python -m design.notebooks.generate_data` first.")
            data = path.read_bytes()
            base = f"/{ws_id}/{lh_id}/Files/raw/{name}.csv"
            # 1) create file
            conn.request("PUT", base + "?resource=file", headers=hdr)
            conn.getresponse().read()
            # 2) append
            h2 = dict(hdr); h2["Content-Type"] = "application/octet-stream"
            conn.request("PATCH", base + "?action=append&position=0", body=data, headers=h2)
            conn.getresponse().read()
            # 3) flush
            conn.request("PATCH", base + f"?action=flush&position={len(data)}", headers=hdr)
            r = conn.getresponse(); r.read()
            print(f"   uploaded raw/{name}.csv ({len(data):,} bytes) [{r.status}]")
    finally:
        conn.close()


def main():
    cfg = load_config(); state = load_state()
    api = cfg["fabric_api_base"]; ws = state["workspace_id"]; name = cfg["lakehouse_name"]
    token = get_fabric_token(); h = fabric_headers(token)

    print_step(1, 3, f"Create or find Lakehouse '{name}'")
    lh_id = None
    try:
        lh_id = find_item(token, api, ws, name, "Lakehouse")["id"]
        print(f"   reusing: {lh_id}")
    except RuntimeError:
        r = requests.post(f"{api}/workspaces/{ws}/items", headers=h,
                          json={"displayName": name, "type": "Lakehouse",
                                "description": "Zava Media batch star schema (plan / delivery / billing)"},
                          timeout=60)
        if r.status_code in (200, 201):
            lh_id = r.json()["id"]
        elif r.status_code == 202:
            op = r.headers.get("x-ms-operation-id")
            if op: poll_operation(token, api, op)
            lh_id = find_item(token, api, ws, name, "Lakehouse")["id"]
        else:
            raise RuntimeError(f"Create Lakehouse failed ({r.status_code}): {r.text[:300]}")
        print(f"   created: {lh_id}")

    print_step(2, 3, f"Upload {len(BATCH_TABLES)} batch CSVs to OneLake Files/raw/")
    upload_files(ws, lh_id, get_storage_token())

    print_step(3, 3, "Persist state (+ SQL endpoint)")
    det = requests.get(f"{api}/workspaces/{ws}/lakehouses/{lh_id}", headers=h, timeout=60).json()
    sql = det.get("properties", {}).get("sqlEndpointProperties", {}).get("connectionString")
    state["lakehouse_id"] = lh_id
    if sql: state["lakehouse_sql_endpoint"] = sql
    save_state(state)
    print(f"   lakehouse_id = {lh_id}")
    print("\nOK. Next: deploy_setup_notebook.py to create Delta tables from the CSVs.")


if __name__ == "__main__":
    main()
