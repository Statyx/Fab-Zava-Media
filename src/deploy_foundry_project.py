"""
Step 11 — the Foundry project that will host the orchestrator.

Creates, idempotently:
  1. the resource group
  2. the Foundry (AI Services) account, with a system-assigned identity
  3. the project inside it
  4. one model deployment for the agents to run on

Region rule, enforced here rather than left to a comment: the Foundry project must sit
in the SAME region as the Fabric capacity. Every question in this demo crosses from
Foundry into Fabric and back; a cross-region project adds a network hop to an already
multi-hop path (supervisor -> A2A -> Fabric tool -> data agent -> DAX). It also splits
the data residency story in two, which is the first thing a European media agency asks
about.

Usage:
    python deploy_foundry_project.py
    python deploy_foundry_project.py --delete
"""

import argparse
import sys

from platform_env import bootstrap
bootstrap()

from helpers import load_config, load_state, save_state, print_step
from foundry_common import (
    AzError, account_scope, arm_get, arm_request, az_json, az_json_probe, banner, die,
    project_endpoint, project_scope, require, wait_for,
)

TOTAL = 5


def _subscription_id() -> str:
    acct = az_json(["account", "show"])
    if not acct:
        die("`az account show` returned nothing. Run `az login` first.")
    return acct["id"]


def ensure_resource_group(sub: str, rg: str, region: str):
    existing = az_json_probe(["group", "show", "-n", rg])
    if existing:
        have = (existing.get("location") or "").replace(" ", "").lower()
        if have != region:
            die(f"Resource group '{rg}' is in '{have}', config wants '{region}'. "
                f"Pick a different resource_group rather than moving this one.")
        print(f"    resource group '{rg}' already exists ({have})")
        return
    az_json(["group", "create", "-n", rg, "-l", region])
    print(f"    created resource group '{rg}' in {region}")


def ensure_account(sub: str, rg: str, account: str, region: str):
    """
    The Foundry resource. `--custom-domain` is not cosmetic: it is what produces the
    `{account}.services.ai.azure.com` hostname that every data-plane call and every A2A
    base path is built from. Without it there is no stable endpoint to point a
    connection at.
    """
    existing = arm_get(account_scope(sub, rg, account))
    if existing:
        have = (existing.get("location") or "").replace(" ", "").lower()
        if have != region:
            die(f"Foundry account '{account}' is in '{have}', config wants '{region}'.")
        print(f"    Foundry account '{account}' already exists ({have})")
        return existing

    print(f"    creating Foundry account '{account}' in {region} ...")
    az_json([
        "cognitiveservices", "account", "create",
        "-n", account, "-g", rg, "-l", region,
        "--kind", "AIServices", "--sku", "S0",
        "--custom-domain", account,
        "--assign-identity",
        "--yes",
    ])
    return wait_for(lambda: arm_get(account_scope(sub, rg, account)),
                    f"account '{account}' to provision")


def ensure_project(sub: str, rg: str, account: str, project: str, region: str):
    scope = project_scope(sub, rg, account, project)
    existing = arm_get(scope)
    if existing:
        print(f"    project '{project}' already exists")
        return existing

    print(f"    creating project '{project}' ...")
    arm_request("PUT", scope, {
        "location": region,
        "identity": {"type": "SystemAssigned"},
        "properties": {
            "displayName": project,
            "description": "Zava Media — orchestrator over the Fabric data agent and the contract corpus.",
        },
    })
    return wait_for(lambda: arm_get(scope), f"project '{project}' to provision")


def ensure_deployment(rg: str, account: str, deployment: str,
                      model: str, version: str, capacity: int):
    """
    One model deployment. The agents reference it by DEPLOYMENT name, not by model id —
    a rename here silently breaks every agent version that quotes the old one.

    GlobalStandard is the right default for a demo: no reserved capacity, no regional
    quota fight, and it is available in Sweden Central.
    """
    existing = az_json_probe(["cognitiveservices", "account", "deployment", "show",
                              "-n", account, "-g", rg, "--deployment-name", deployment])
    if existing:
        print(f"    model deployment '{deployment}' already exists")
        return existing

    print(f"    creating model deployment '{deployment}' ({model} {version}) ...")
    try:
        return az_json([
            "cognitiveservices", "account", "deployment", "create",
            "-n", account, "-g", rg,
            "--deployment-name", deployment,
            "--model-name", model,
            "--model-version", version,
            "--model-format", "OpenAI",
            "--sku-name", "GlobalStandard",
            "--sku-capacity", str(capacity),
        ])
    except AzError as exc:
        msg = str(exc)
        if "quota" in msg.lower() or "capacity" in msg.lower():
            die(f"Model deployment refused for quota reasons:\n{msg}\n\n"
                f"Lower foundry.model_capacity in config.yaml, or request quota for "
                f"'{model}' in this region.")
        raise


def delete_all(sub: str, rg: str, account: str, project: str):
    scope = project_scope(sub, rg, account, project)
    if arm_get(scope):
        print(f"    deleting project '{project}' ...")
        arm_request("DELETE", scope)
    if arm_get(account_scope(sub, rg, account)):
        print(f"    deleting account '{account}' ...")
        az_json(["cognitiveservices", "account", "delete", "-n", account, "-g", rg])
    print("    the resource group is left in place on purpose — it may hold other work")


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy the Zava Media Foundry project")
    parser.add_argument("--delete", action="store_true",
                        help="tear the project and account down (keeps the resource group)")
    args = parser.parse_args()

    banner("Zava Media - Foundry project")

    config = load_config()
    state = load_state()

    region = require(config, "foundry", "region")
    capacity_region = (config.get("capacity_region") or "").replace(" ", "").lower()
    if capacity_region and capacity_region != region:
        die(f"foundry.region is '{region}' but capacity_region is '{capacity_region}'.\n"
            f"Keep them equal: every demo question crosses this boundary, and a "
            f"cross-region hop costs latency on a path that already has four.")

    rg = require(config, "foundry", "resource_group")
    account = require(config, "foundry", "account_name")
    project = require(config, "foundry", "project_name")
    deployment = require(config, "foundry", "model_deployment_name")
    model = require(config, "foundry", "model_name")
    version = require(config, "foundry", "model_version")
    capacity = int(config["foundry"].get("model_capacity", 50))

    print_step(1, TOTAL, "Resolving the subscription")
    sub = _subscription_id()
    print(f"    subscription {sub}")

    if args.delete:
        delete_all(sub, rg, account, project)
        for key in ("foundry_endpoint", "foundry_account_name", "foundry_project_name",
                    "foundry_resource_group", "foundry_subscription_id"):
            state.pop(key, None)
        save_state(state)
        print("\nDeleted.")
        return 0

    print_step(2, TOTAL, f"Resource group '{rg}'")
    ensure_resource_group(sub, rg, region)

    print_step(3, TOTAL, f"Foundry account '{account}'")
    ensure_account(sub, rg, account, region)

    print_step(4, TOTAL, f"Project '{project}'")
    ensure_project(sub, rg, account, project, region)

    print_step(5, TOTAL, f"Model deployment '{deployment}'")
    ensure_deployment(rg, account, deployment, model, version, capacity)

    endpoint = project_endpoint(account, project)
    state.update({
        "foundry_subscription_id": sub,
        "foundry_resource_group": rg,
        "foundry_account_name": account,
        "foundry_project_name": project,
        "foundry_endpoint": endpoint,
        "foundry_model_deployment": deployment,
    })
    save_state(state)

    print(f"\nProject endpoint: {endpoint}")
    print("Read from the account's properties.endpoints[\"AI Foundry API\"] when `az` could")
    print("reach it, else the documented shape. Note that properties.endpoint - singular -")
    print("is the legacy *.cognitiveservices.azure.com host and is NOT the one to use.")
    print("\nNext: python deploy_foundry_connection.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
