#!/usr/bin/env python3
"""
Create the Eventhouse + KQL Database + the pacing_events table (streaming ingestion on).

The Eventhouse carries the LIVE layer: a trailing window of campaign pacing deltas.
The batch star schema lives in the Lakehouse (deploy_lakehouse.py).

Naming: creating an Eventhouse auto-creates a KQL Database with the SAME display name
as the eventhouse. `kql_db_name` in config.yaml is informational — this script resolves
the database that actually exists and records it in state as `kql_db_name`, so the
ontology's TimeSeries binding points at a real database rather than a guessed one.
"""
import os, sys, time
from platform_env import bootstrap
bootstrap()

import requests
from helpers import (load_config, load_state, save_state, get_fabric_token,
                     get_kusto_token, fabric_headers, create_fabric_item,
                     kusto_mgmt, print_step)


def wait_for_kql_db(token, api, ws, eh_name, alt_name=None, tries=20):
    """Return the auto-created KQL database. Accepts either the eventhouse name
    (what Fabric actually uses) or the configured alternative."""
    h = fabric_headers(token)
    wanted = {eh_name}
    if alt_name:
        wanted.add(alt_name)
    for i in range(tries):
        r = requests.get(f"{api}/workspaces/{ws}/items?type=KQLDatabase", headers=h, timeout=60)
        r.raise_for_status()
        for db in r.json().get("value", []):
            if db["displayName"] in wanted:
                return db
        print(f"   waiting for KQL DB ({i+1}/{tries})...")
        time.sleep(10)
    raise RuntimeError(
        f"KQL Database not provisioned (looked for {sorted(wanted)}). "
        f"Check the Eventhouse in the portal.")


def main():
    cfg = load_config(); state = load_state()
    api = cfg["fabric_api_base"]; ws = state["workspace_id"]
    eh_name = cfg["eventhouse_name"]
    token = get_fabric_token()

    print_step(1, 4, f"Create Eventhouse '{eh_name}'")
    if state.get("eventhouse_id"):
        print(f"   reusing: {state['eventhouse_id']}")
    else:
        eh = create_fabric_item(token, api, ws, eh_name, "Eventhouse",
                                "Zava Media live campaign pacing (TimeSeries)")
        state["eventhouse_id"] = eh["id"]; save_state(state)
        print(f"   created: {eh['id']}")

    print_step(2, 4, "Wait for KQL Database + query URI")
    db = wait_for_kql_db(token, api, ws, eh_name, cfg.get("kql_db_name"))
    db_name = db["displayName"]
    state["kql_database_id"] = db["id"]
    state["kql_db_name"] = db_name
    eh_det = requests.get(f"{api}/workspaces/{ws}/eventhouses/{state['eventhouse_id']}",
                          headers=fabric_headers(token), timeout=60).json()
    quri = eh_det["properties"]["queryServiceUri"]
    state["query_service_uri"] = quri; save_state(state)
    print(f"   KQL DB '{db_name}' {db['id']} · {quri}")

    print_step(3, 4, "Create KQL tables")
    ktok = get_kusto_token(quri)
    time.sleep(15)
    for _, t in cfg["kql_tables"].items():
        cols = ", ".join(f"{c['name']}:{c['type']}" for c in t["columns"])
        kusto_mgmt(quri, ktok, db_name, f".create-merge table {t['name']} ({cols})")
        print(f"   table {t['name']} ready")

    print_step(4, 4, "Enable streaming ingestion")
    for _, t in cfg["kql_tables"].items():
        try:
            kusto_mgmt(quri, ktok, db_name,
                       f".alter table {t['name']} policy streamingingestion enable")
            print(f"   streaming on {t['name']}")
        except Exception as e:
            print(f"   ! {t['name']}: {e}")

    print("\nOK. Next: preload_pacing.py")


if __name__ == "__main__":
    main()
