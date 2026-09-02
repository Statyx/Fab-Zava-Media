#!/usr/bin/env python3
"""
One-shot idempotent orchestrator for the Zava Media demo.

Runs every deploy step in dependency-safe order. Each step is idempotent (it reuses
items recorded in state.json), so re-running resumes rather than duplicating. It ends
with a warm-up so the first live demo query — Fabric auth plus the Eventhouse cold
start from idle capacity — is paid for off-stage rather than in front of the client.

USAGE
  python deploy_all.py                     # full deploy, then warm-up
  python deploy_all.py --from ontology     # resume from a given step to the end
  python deploy_all.py ontology graph      # run only these steps (canonical order kept)
  python deploy_all.py --skip generate_data
  python deploy_all.py --warmup            # warm-up only (no deploy)
  python deploy_all.py --no-warmup         # deploy only

TENANT: az silently flips to another tenant. Set `az_subscription` in config.yaml
(your Azure subscription NAME — never commit it) or export ZAVA_AZ_SUBSCRIPTION, and
this script runs `az account set` first. Without it you get 404 EntityNotFound while
authenticated against the wrong tenant, which looks exactly like a permissions problem.

WHAT THIS DOES NOT DEPLOY: the Foundry side. The orchestrator agent (Zava_Media_Agent),
its connection to this Fabric data agent and the contracts knowledge base are a separate
deploy — see docs/ARCHITECTURE.md. This script stops at the Fabric boundary.
"""
import os, sys
from platform_env import bootstrap
bootstrap()

import argparse
import importlib
import subprocess
import time
import requests
from platform_env import AZ_NEEDS_SHELL, find_executable
from helpers import (load_config, load_state, get_fabric_token, fabric_headers,
                     get_kusto_token, print_step)

# Canonical deploy order (name -> module). Each module exposes main().
# The order encodes real dependencies:
#   lakehouse tables must exist before the ontology binds to them;
#   the ontology must exist before the graph can be populated;
#   the semantic model must exist before the data agent can point at it.
STEPS = [
    ("generate_data",   "generate_data"),
    ("workspace",       "deploy_workspace"),
    ("lakehouse",       "deploy_lakehouse"),
    ("setup_notebook",  "deploy_setup_notebook"),
    ("eventhouse",      "deploy_eventhouse"),
    ("preload_pacing",  "preload_pacing"),
    ("ontology",        "deploy_ontology"),
    ("graph",           "deploy_graph"),
    ("semantic_model",  "deploy_semantic_model"),
    ("data_agent",      "deploy_data_agent"),
    # ── Foundry half ────────────────────────────────────────────────
    # Everything below needs a PUBLISHED Fabric data agent, so it cannot move above
    # data_agent: a connection can only point at a published artifact, and a draft has
    # no stable answer surface to bind to.
    ("foundry_project",    "deploy_foundry_project"),
    ("foundry_connection", "deploy_foundry_connection"),
    ("foundry_agents",     "deploy_foundry_agents"),
]
STEP_NAMES = [name for name, _ in STEPS]
FOUNDRY_STEPS = [name for name, _ in STEPS if name.startswith("foundry_")]
FABRIC_STEPS = [name for name in STEP_NAMES if name not in FOUNDRY_STEPS]


def ensure_tenant(cfg):
    """Pin az to the right subscription/tenant (az silently flips to corp)."""
    sub = cfg.get("az_subscription")
    if not sub:
        print("⚠  No 'az_subscription' in config.yaml (or ZAVA_AZ_SUBSCRIPTION) — ensure az is on "
              "the correct tenant (404 EntityNotFound = wrong tenant, not a permissions problem).")
        return
    try:
        subprocess.check_call(["az", "account", "set", "--subscription", sub],
                              shell=AZ_NEEDS_SHELL)
        print(f"✓  az subscription set to '{sub}'")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        if find_executable("az") is None:
            raise RuntimeError(
                "Azure CLI (`az`) was not found on PATH. Install it and run `az login`."
            ) from e
        raise RuntimeError(f"Could not set az subscription '{sub}': {e}")


def select_steps(args):
    if args.steps:
        unknown = [s for s in args.steps if s not in STEP_NAMES]
        if unknown:
            raise SystemExit(f"Unknown step(s): {unknown}. Valid: {STEP_NAMES}")
        chosen = [s for s in STEP_NAMES if s in args.steps]  # keep canonical order
    elif args.from_step:
        if args.from_step not in STEP_NAMES:
            raise SystemExit(f"Unknown --from step '{args.from_step}'. Valid: {STEP_NAMES}")
        chosen = STEP_NAMES[STEP_NAMES.index(args.from_step):]
    elif args.fabric_only:
        chosen = list(FABRIC_STEPS)
    elif args.foundry_only:
        chosen = list(FOUNDRY_STEPS)
    else:
        chosen = list(STEP_NAMES)
    skip = set(s.strip() for s in (args.skip or "").split(",") if s.strip())
    return [s for s in chosen if s not in skip]


def run_steps(names):
    mod_of = dict(STEPS)
    total = len(names)
    for idx, name in enumerate(names, 1):
        print_step(idx, total, f"STEP: {name}  (module {mod_of[name]})")
        mod = importlib.import_module(mod_of[name])
        mod.main()
    print(f"\n✓  {total} step(s) completed.")


def warm_up(cfg, state):
    """Pay the first-query latency off-stage: Fabric auth + Eventhouse cold start."""
    print_step(1, 2, "Warm-up: Fabric workspace + token")
    try:
        api = cfg["fabric_api_base"]; ws = state["workspace_id"]
        h = fabric_headers(get_fabric_token())
        items = requests.get(f"{api}/workspaces/{ws}/items", headers=h,
                             timeout=60).json().get("value", [])
        print(f"   Fabric OK — {len(items)} items in workspace.")
    except Exception as e:
        print(f"   (warm-up Fabric skipped: {e})")

    print_step(2, 2, "Warm-up: Eventhouse/KQL query (cold start)")
    try:
        quri = state["query_service_uri"]
        # The KQL DB that was actually created, not the one config guessed at.
        db = state.get("kql_db_name") or cfg.get("kql_db_name") or cfg["eventhouse_name"]
        ktok = get_kusto_token(quri)
        t0 = time.time()
        r = requests.post(f"{quri}/v1/rest/query",
                          headers={"Authorization": f"Bearer {ktok}",
                                   "Content-Type": "application/json; charset=utf-8"},
                          json={"db": db, "csl": "pacing_events | summarize c=count()"},
                          timeout=120)
        r.raise_for_status()
        rows = r.json().get("Tables", [{}])[0].get("Rows", [[None]])
        print(f"   Kusto OK — pacing_events count={rows[0][0]} in {time.time()-t0:.1f}s.")
    except Exception as e:
        print(f"   (warm-up Kusto skipped: {e})")


def main():
    p = argparse.ArgumentParser(description="Zava Media deploy orchestrator")
    p.add_argument("steps", nargs="*",
                   help=f"run only these steps (order fixed). Valid: {STEP_NAMES}")
    p.add_argument("--from", dest="from_step", help="resume from this step to the end")
    p.add_argument("--skip", help="comma-separated steps to skip")
    p.add_argument("--fabric-only", dest="fabric_only", action="store_true",
                   help="stop after the published data agent (skip the Foundry half)")
    p.add_argument("--foundry-only", dest="foundry_only", action="store_true",
                   help="run only the Foundry half (needs a published data agent in state)")
    p.add_argument("--warmup", action="store_true", help="run warm-up only (no deploy)")
    p.add_argument("--no-warmup", dest="no_warmup", action="store_true",
                   help="deploy without warm-up")
    args = p.parse_args()

    cfg = load_config()
    ensure_tenant(cfg)

    if args.warmup:
        warm_up(cfg, load_state())
        return

    names = select_steps(args)
    print(f"Plan: {names}")
    run_steps(names)

    if not args.no_warmup:
        warm_up(cfg, load_state())

    agent = cfg.get("data_agent_name", "Zava_Media_Analyst")
    orch = cfg.get("foundry", {}).get("orchestrator_agent_name", "Zava_Media_Agent")
    print(f"\n🎯  Zava Media ready on the Fabric side. Ask {agent}: "
          f"\"What did we over-deliver for Contoso Mobility in Spain in 2026-Q3?\" "
          f"→ it returns the figure and says the contractual entitlement is out of its scope. "
          f"That refusal is the handoff: {orch} (Foundry) adds the clause.")


if __name__ == "__main__":
    main()
