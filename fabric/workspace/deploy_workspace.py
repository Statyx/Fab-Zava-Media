#!/usr/bin/env python3
"""
Deploy the Fabric workspace (config `workspace_name`) and assign it to the capacity.
Idempotent: finds an existing workspace by name; otherwise creates + assigns capacity.
Saves workspace_id to state.json.

REGION: the capacity's home region is the data residency of everything created here.
This demo runs on a Sweden Central capacity, which sits inside the EU Data Boundary —
so the Azure OpenAI deployment backing Fabric Copilot / data agents is also EU-hosted
and NO cross-geo processing switch is needed. See docs/ARCHITECTURE.md § 5.
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import requests
from fabric._shared.helpers import (load_config, load_state, save_state, get_fabric_token,
                     fabric_headers, poll_operation, print_step,
                     require_config)

DESCRIPTION = ("Zava Media demo — media-agency delivery vs plan, Fabric IQ ontology "
               "and a data agent answering the numbers behind a contractual question.")


def capacity_region(api, headers, capacity_id):
    """Return the capacity's region, or None if it cannot be read.

    The capacities API returns a DISPLAY name ('Sweden Central'); config files and
    ARM use the compact form ('swedencentral'). Normalise before comparing or a
    correct setup fails the check.
    """
    try:
        r = requests.get(f"{api}/capacities", headers=headers, timeout=60)
        r.raise_for_status()
        for c in r.json().get("value", []):
            if c.get("id", "").lower() == capacity_id.lower():
                return c.get("region"), c.get("sku"), c.get("state")
    except Exception:
        pass
    return None, None, None


def main():
    cfg = load_config(); state = load_state()
    api = require_config(cfg, "fabric_api_base")
    name = require_config(cfg, "workspace_name")
    cap = require_config(cfg, "capacity_id")
    token = get_fabric_token(); h = fabric_headers(token)

    print_step(1, 4, f"Check capacity {cap[:8]}…")
    region, sku, cstate = capacity_region(api, h, cap)
    if region:
        expected = (cfg.get("capacity_region") or "").replace(" ", "").lower()
        actual = region.replace(" ", "").lower()
        print(f"   {sku} · {region} · {cstate}")
        if expected and expected != actual:
            print(f"   ⚠  config says capacity_region '{cfg['capacity_region']}' "
                  f"but the capacity is in '{region}'. OneLake residency follows the "
                  f"CAPACITY, not the config file — fix config.yaml.")
        if cstate and cstate != "Active":
            print(f"   ⚠  capacity state is '{cstate}', not Active — deploys will fail.")
    else:
        print("   (could not read the capacity — continuing; assign will report the truth)")

    print_step(2, 4, f"Find or create workspace '{name}'")
    ws_id = None
    r = requests.get(f"{api}/workspaces", headers=h, timeout=60)
    r.raise_for_status()
    for w in r.json().get("value", []):
        if w.get("displayName") == name:
            ws_id = w["id"]; print(f"   reusing: {ws_id}"); break
    if not ws_id:
        cr = requests.post(f"{api}/workspaces", headers=h,
                           json={"displayName": name, "description": DESCRIPTION},
                           timeout=60)
        if cr.status_code in (200, 201):
            ws_id = cr.json()["id"]
        elif cr.status_code == 202:
            op = cr.headers.get("x-ms-operation-id")
            if op: poll_operation(token, api, op)
            r2 = requests.get(f"{api}/workspaces", headers=h, timeout=60)
            ws_id = next(w["id"] for w in r2.json()["value"] if w["displayName"] == name)
        else:
            raise RuntimeError(f"Create workspace failed ({cr.status_code}): {cr.text[:400]}")
        print(f"   created: {ws_id}")

    print_step(3, 4, "Assign capacity")
    ac = requests.post(f"{api}/workspaces/{ws_id}/assignToCapacity", headers=h,
                       json={"capacityId": cap}, timeout=60)
    if ac.status_code in (200, 202):
        print(f"   capacity assigned ({cap[:8]}…)")
    elif ac.status_code == 400 and "already" in ac.text.lower():
        print("   capacity already assigned")
    else:
        print(f"   assignToCapacity -> {ac.status_code}: {ac.text[:200]}")

    print_step(4, 4, "Persist state")
    state["workspace_id"] = ws_id
    save_state(state)
    print(f"   workspace_id = {ws_id}")
    print("\nOK. Next: deploy_lakehouse.py")


if __name__ == "__main__":
    main()
