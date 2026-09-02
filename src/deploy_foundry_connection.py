"""
Step 12 — the project connection that lets Foundry call the Fabric data agent.

The brain documents this as a portal flow: open the published data agent in Fabric, read
two GUIDs out of the browser URL, and paste them into *Tools -> Connect a tool*. It also
calls that path out as "brittle and unautomatable ... script the connection creation if
you can".

We can. Both GUIDs are already in state.json, put there by the Fabric deploy:

    workspace_id    <- deploy_workspace.py
    data_agent_id   <- deploy_data_agent.py

which is the same pair the URL `.../groups/{workspace_id}/aiskills/{data_agent_id}`
exposes. So nothing is read off a screen.

⚠️ PROVEN NEGATIVE — tenant-verified 2026-09-02, Sweden Central.

ARM **cannot** create the connection the Fabric data-agent tool consumes. This is not a
missing field; the category does not exist on the control plane:

  * `MicrosoftFabricPreviewTool` fails at RUNTIME with
        No CustomKeys connection found for AzureFabric
  * ARM has no `AzureFabric` category. Every api-version tried (2025-04-01-preview,
    2025-06-01, 2025-10-01-preview, …) answers "unable to deserialize request body".
  * The one Fabric category ARM does accept is `MicrosoftFabric`, and it answers
        AuthType for MicrosoftFabric Connection can only be AAD, UserEntraToken
    so it can never be the CustomKeys connection the tool is looking for.
  * The data plane is read-only for connections (`get`, `get_default`, `list` — no create),
    so there is no second programmatic route.

⚠️ AND THE TRAP: ARM **accepts** `MicrosoftFabric` and returns 200. A created connection
therefore looks like success and fails only later, inside a model run, in a script that
has already done six other things. "ARM stored it" is not an oracle for "the tool can use
it" — the only oracle is a real question routed through the tool.

⇒ The portal step below is REQUIRED, not a convenience fallback. This script still writes
the ARM connection because it is harmless and keeps the name reserved, then prints the
portal steps every time.

Usage:
    python deploy_foundry_connection.py
    python deploy_foundry_connection.py --portal-steps
    python deploy_foundry_connection.py --delete
"""

import argparse
import sys

from platform_env import bootstrap
bootstrap()

from helpers import load_config, load_state, save_state, print_step, require_state
from foundry_common import (
    AzError, arm_get, arm_request, banner, die, project_scope, require,
)

TOTAL = 3

# Tried in order. The first one ARM accepts wins and is written to state, so the second
# run is a single call. `FabricDataAgent` mirrors the tool name in the current catalog;
# `MicrosoftFabric` mirrors the portal label; `CustomKeys` is the generic escape hatch.
CANDIDATE_CATEGORIES = ["FabricDataAgent", "MicrosoftFabric", "CustomKeys"]


def portal_steps(workspace_id: str, agent_id: str, name: str) -> str:
    return f"""
Portal fallback — this takes about 30 seconds.

  1. Foundry portal, your project, with the *New Foundry* toggle ON.
  2. Tools -> Tools -> Connect a tool -> Microsoft Fabric Data Agent -> Add tool.
  3. Connection: *Add a new connection*, then:

         Name           {name}
         Workspace ID   {workspace_id}
         Artifact ID    {agent_id}

  4. Connect.

The name is what the code resolves at runtime, so it must match config.yaml exactly.
Then re-run:  python deploy_foundry_agents.py
"""


def connection_scope(state, name: str) -> str:
    return (project_scope(state["foundry_subscription_id"],
                          state["foundry_resource_group"],
                          state["foundry_account_name"],
                          state["foundry_project_name"]) + f"/connections/{name}")


def build_body(category: str, workspace_id: str, agent_id: str) -> dict:
    """
    The target carries both GUIDs in the same shape the Fabric URL uses, which is what
    the portal form ends up storing. `isSharedToAll` keeps the connection visible to the
    whole project rather than to its creator alone — otherwise the agent runs under a
    different identity and cannot see it.
    """
    body = {
        "properties": {
            "category": category,
            "target": f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/aiskills/{agent_id}",
            "authType": "AAD",
            "isSharedToAll": True,
            "metadata": {
                "workspaceId": workspace_id,
                "artifactId": agent_id,
            },
        }
    }
    if category == "CustomKeys":
        body["properties"]["authType"] = "CustomKeys"
        body["properties"]["credentials"] = {"keys": {}}
    return body


def create_connection(state, name: str, workspace_id: str, agent_id: str) -> str:
    scope = connection_scope(state, name)

    existing = arm_get(scope)
    if existing:
        cat = (existing.get("properties") or {}).get("category", "?")
        print(f"    connection '{name}' already exists (category '{cat}')")
        return cat

    known = state.get("fabric_connection_category")
    order = ([known] if known else []) + [c for c in CANDIDATE_CATEGORIES if c != known]

    errors = []
    for category in order:
        try:
            print(f"    trying category '{category}' ...")
            arm_request("PUT", scope, build_body(category, workspace_id, agent_id))
            print(f"    accepted with category '{category}'")
            return category
        except AzError as exc:
            errors.append(f"  {category}: {str(exc)[:220]}")

    print("\nEvery candidate category was rejected by ARM:\n" + "\n".join(errors))
    print(portal_steps(workspace_id, agent_id, name))
    die("Could not create the Fabric connection from ARM. Use the portal steps above.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Connect the Fabric data agent to Foundry")
    parser.add_argument("--portal-steps", action="store_true",
                        help="print the manual portal instructions and exit")
    parser.add_argument("--delete", action="store_true", help="remove the connection")
    args = parser.parse_args()

    banner("Zava Media - Fabric data agent connection")

    config = load_config()
    state = load_state()

    name = require(config, "foundry", "fabric_connection_name")
    workspace_id = require_state(state, "workspace_id")
    agent_id = state.get("data_agent_id")

    if args.portal_steps:
        print(portal_steps(workspace_id, agent_id or "<run deploy_data_agent.py first>", name))
        return 0

    print_step(1, TOTAL, "Checking prerequisites")
    for key in ("foundry_subscription_id", "foundry_resource_group",
                "foundry_account_name", "foundry_project_name"):
        if not state.get(key):
            die(f"state.json has no '{key}'. Run deploy_foundry_project.py first.")
    if not agent_id:
        die("state.json has no 'data_agent_id'. Run deploy_data_agent.py first.\n"
            "A connection can only point at a PUBLISHED Fabric data agent; a draft has "
            "no stable answer surface.")
    print(f"    workspace  {workspace_id}")
    print(f"    data agent {agent_id}")

    if args.delete:
        scope = connection_scope(state, name)
        if arm_get(scope):
            arm_request("DELETE", scope)
            print(f"    deleted connection '{name}'")
        else:
            print(f"    connection '{name}' does not exist")
        state.pop("fabric_connection_category", None)
        save_state(state)
        return 0

    print_step(2, TOTAL, f"Creating connection '{name}'")
    category = create_connection(state, name, workspace_id, agent_id)

    print_step(3, TOTAL, "Recording what worked")
    state["fabric_connection_name"] = name
    state["fabric_connection_category"] = category
    # ARM acceptance proves storage, never usability. Kept false until a real run through
    # the tool says otherwise, so no later step can mistake "created" for "working".
    state["fabric_connection_tool_verified"] = False
    save_state(state)
    print(f"    state.fabric_connection_category = '{category}'")

    print(f"""
⚠️  ARM HAS STORED A CONNECTION. THE FABRIC TOOL STILL CANNOT USE IT.

This is a proven limitation, not a suspicion (tenant-verified, Sweden Central):
the Fabric data-agent tool resolves a CustomKeys connection of category 'AzureFabric',
and ARM has no such category at any api-version. What ARM accepts — 'MicrosoftFabric' —
is restricted to AAD / UserEntraToken, so it can never be that connection.

Left as-is, the first agent run fails with:
    No CustomKeys connection found for AzureFabric

YOU MUST CREATE IT ONCE IN THE PORTAL, under the SAME name ('{name}'), so that
deploy_foundry_agents.py keeps resolving it by name and nothing else changes.
{portal_steps(workspace_id, agent_id, name)}
Next: python deploy_foundry_agents.py""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
