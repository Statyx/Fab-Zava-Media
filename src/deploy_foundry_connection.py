"""
Step 12 — the project connection that lets Foundry call the Fabric data agent.

WHAT THIS SCRIPT USED TO SAY, AND WHY IT WAS WRONG (corrected 2026-09-03)
    An earlier version of this file carried a section headed "PROVEN NEGATIVE" that
    concluded the portal step was REQUIRED and unautomatable. Half of that was true and
    the conclusion did not follow from it.

    True, still true, and re-verified:
        `MicrosoftFabricPreviewTool` resolves a **CustomKeys** connection of category
        **`AzureFabric`**, and ARM cannot create one. Every api-version rejects the body,
        and the one Fabric category ARM does accept — `MicrosoftFabric` — is restricted to
        AAD / UserEntraToken, so it can never be that connection.

    The error that misled me:
            No CustomKeys connection found for AzureFabric
        names a category you never create. I searched ARM for `AzureFabric`, correctly
        found nothing, and concluded the goal was unreachable. But `AzureFabric` is the
        name of ONE path to the goal, not the goal.

    The goal — Foundry asking the Fabric data agent a question — is reachable from code
    through a DIFFERENT tool with a DIFFERENT connection category:

        MicrosoftFabricPreviewTool  <- CustomKeys / AzureFabric   ... portal only
        FabricIQPreviewTool         <- RemoteTool / GenericProtocol ... ARM, scriptable

    The second one reaches the same published data agent over its MCP endpoint. It is what
    this script now creates, and it needs no portal at all.

THE ENDPOINT
    A published Fabric data agent exposes an MCP server at

        {fabric_api_base}/mcp/workspaces/{workspace_id}/dataagents/{agent_id}/agent

    Verified live on this tenant: `initialize` returns 200 with
    `serverInfo.name = "DataAgent MCP Server"`, and `tools/list` returns one tool named
    `DataAgent_<agent name>`. Note the shape — no `dataPlane` segment, and `dataagents`
    (lowercase, plural) where the generic item route would say `items`.

WHAT MAKES THE CONNECTION ACCEPTABLE TO THE TOOL
    `metadata.type = "fabric_iq_preview"`. No document mentions it. Without it the
    connection is created, resolves by name, and the tool still refuses it. It was read
    back off a connection the portal had made, then reproduced by hand.

    Likewise `audience`: the azd docs show `https://analysis.windows.net/powerbi/api`;
    the connection that actually works carries the Fabric audience. Prefer what the
    service produced over what the document says.

WHAT CHANGES FOR THE AGENT
    The two bindings are NOT interchangeable and this one costs you something. The Fabric
    data agent's own instructions do not travel over MCP — the metric definitions, the
    populations, the guard rails all stay behind. `deploy_foundry_agents.py` therefore
    carries them in the analyst prompt instead. Read the note there before changing it.

Usage:
    python deploy_foundry_connection.py
    python deploy_foundry_connection.py --portal-steps    # the legacy manual path
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

TOTAL = 4

# The connection carries identity only; `server_url` on the tool selects the Fabric item.
FABRIC_AUDIENCE = "https://api.fabric.microsoft.com"
FABRIC_API_BASE = "https://api.fabric.microsoft.com/v1"

# The marker that makes FabricIQPreviewTool accept the connection. Undocumented; read off
# a working portal-made connection. A connection without it exists but the tool refuses it.
CONNECTION_METADATA = {"type": "fabric_iq_preview"}


def mcp_server_url(workspace_id: str, agent_id: str) -> str:
    """The MCP endpoint of a PUBLISHED Fabric data agent.

    Shape matters more than the names in it. The generic Fabric item route is
    `/mcp/dataPlane/workspaces/{ws}/items/{id}/...`; the data agent is NOT on it. It drops
    `dataPlane` and uses `dataagents` instead of `items`. Probing sixteen trailing segments
    on the generic route returns sixteen 404s and proves only that you varied one axis.
    """
    return f"{FABRIC_API_BASE}/mcp/workspaces/{workspace_id}/dataagents/{agent_id}/agent"


def portal_steps(workspace_id: str, agent_id: str, name: str) -> str:
    """The legacy manual path. Kept because it is what the CustomKeys tool needs.

    You only need this if you deliberately switch the agent back to
    `MicrosoftFabricPreviewTool`, which inherits the data agent's own semantics.
    """
    return f"""
Portal path — only needed for the CustomKeys / MicrosoftFabricPreviewTool binding.

  1. Foundry portal, your project, with the *New Foundry* toggle ON.
  2. Tools -> Tools -> Connect a tool -> Microsoft Fabric Data Agent -> Add tool.
  3. Connection: *Add a new connection*, then:

         Name           {name}
         Workspace ID   {workspace_id}
         Artifact ID    {agent_id}

  4. Connect.

The default path in this repo does NOT need any of the above.
"""


def connection_scope(state, name: str) -> str:
    return (project_scope(state["foundry_subscription_id"],
                          state["foundry_resource_group"],
                          state["foundry_account_name"],
                          state["foundry_project_name"]) + f"/connections/{name}")


def build_body(server_url: str) -> dict:
    """The exact ARM payload that creates a working Fabric IQ connection.

    Every field was read back off a connection the portal had made, not guessed.
    `isSharedToAll` false matches what the portal produces; the agent runs under the
    project identity, which already sees it.
    """
    return {
        "properties": {
            "category": "RemoteTool",
            "group": "GenericProtocol",
            "authType": "UserEntraToken",
            "audience": FABRIC_AUDIENCE,
            "target": server_url,
            "isSharedToAll": False,
            "useWorkspaceManagedIdentity": False,
            "metadata": dict(CONNECTION_METADATA),
        }
    }


def create_connection(state, name: str, server_url: str) -> None:
    scope = connection_scope(state, name)
    existing = arm_get(scope)

    if existing:
        props = existing.get("properties") or {}
        cat = props.get("category", "?")
        meta_type = (props.get("metadata") or {}).get("type")
        target = props.get("target")

        # An existing connection of the OLD category is worse than no connection: it
        # resolves by name, so the agent script binds it and fails at run time instead.
        stale = (cat != "RemoteTool" or meta_type != "fabric_iq_preview"
                 or target != server_url)
        if not stale:
            print(f"    connection '{name}' already correct (RemoteTool, fabric_iq_preview)")
            return

        print(f"    connection '{name}' exists but is stale "
              f"(category '{cat}', metadata.type '{meta_type}')")
        print("    deleting it — a name that resolves to the wrong shape fails at run time,")
        print("    which is much harder to read than a missing connection")
        arm_request("DELETE", scope)

    try:
        arm_request("PUT", scope, build_body(server_url))
    except AzError as exc:
        die(f"ARM refused the connection body:\n  {exc}\n\n"
            "If this is a deserialisation error, the api-version in foundry_common is the\n"
            "first thing to check — this shape is accepted at 2025-06-01.")
    print(f"    created '{name}'  category=RemoteTool  metadata.type=fabric_iq_preview")


def main() -> int:
    parser = argparse.ArgumentParser(description="Connect the Fabric data agent to Foundry")
    parser.add_argument("--portal-steps", action="store_true",
                        help="print the legacy manual portal instructions and exit")
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
        for key in ("fabric_connection_category", "fabric_mcp_server_url",
                    "fabric_connection_tool_verified"):
            state.pop(key, None)
        save_state(state)
        return 0

    print_step(2, TOTAL, "Resolving the data agent's MCP endpoint")
    server_url = mcp_server_url(workspace_id, agent_id)
    print(f"    {server_url}")

    print_step(3, TOTAL, f"Creating connection '{name}'")
    create_connection(state, name, server_url)

    print_step(4, TOTAL, "Recording what worked")
    state["fabric_connection_name"] = name
    state["fabric_connection_category"] = "RemoteTool"
    state["fabric_mcp_server_url"] = server_url
    # ARM acceptance proves storage, never usability. Kept false until a real question has
    # been routed through the tool, so no later step can mistake "created" for "working".
    state["fabric_connection_tool_verified"] = False
    save_state(state)
    print("    state.fabric_connection_category = 'RemoteTool'")
    print("    state.fabric_mcp_server_url      = (above)")

    print("\n    No portal step is required for this binding.")
    print("    Next: python deploy_foundry_agents.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
