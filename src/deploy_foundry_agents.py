"""
Step 13 — the two Foundry agents.

    Zava_Media_Contracts   subordinate. Owns the contract corpus. Reached over A2A.
    Zava_Media_Agent       supervisor. Owns routing and the answer. Reached by the user.

WHY THE SUBORDINATE EXISTS AT ALL
---------------------------------
The obvious design is one supervisor holding the Fabric data agent tool AND a
`file_search` over data/contracts/. That design is documented to fail on a live tenant,
with three isolating runs behind the finding:

    file_search alone            -> fires, correct
    connection tool + file_search -> the connection tool NEVER fires; a dozen-plus
                                     file_search calls instead
    ... plus tool_choice="required" -> still file_search

Cause: `file_search` describes its own purpose to the model, while a connection-backed
tool surfaces only under its connection name, which says nothing about what it fronts.
The model picks the tool it can read. Naming the tool in the prompt did not fix it
(two attempts). The fix is architectural: put the corpus behind A2A so that BOTH tools
are opaque and are told apart by name alone.

Source: Azure-Brain/Foundry-Brain/agents/foundry-orchestration-agent/known_issues.md,
"a2a_preview and file_search do not coexist on one agent" (tenant-observed 2026-08).

For this demo that failure is not cosmetic. The entire commercial argument is that the
NUMBER comes from Fabric and the CLAUSE comes from the contracts. A supervisor that
answers "+12%" out of a PDF has destroyed the point while looking perfectly fluent.

Usage:
    python deploy_foundry_agents.py
    python deploy_foundry_agents.py --skip-upload      # corpus unchanged
    python deploy_foundry_agents.py --delete
"""

import argparse
import json
import sys
from pathlib import Path

from platform_env import bootstrap
bootstrap()

from helpers import load_config, load_state, save_state, print_step
from foundry_common import (
    AzError, a2a_base_path, agents_request, arm_get, arm_request, banner, die,
    project_scope, require,
)

TOTAL = 7
CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "data" / "contracts"


# ─────────────────────────────────────────────────────────────────────────────
# The subordinate. A thin wrapper: one corpus, one job, no ambition beyond it.
# ─────────────────────────────────────────────────────────────────────────────
CONTRACTS_INSTRUCTIONS = """\
You are the Zava Media contracts agent. You answer from the media-buying contracts \
corpus and from nothing else.

WHAT YOU DO
- Given an advertiser, a market and a subject (over-delivery, under-delivery, \
make-good, penalty, invoicing, audit), find the governing clause and return it.
- Quote the clause verbatim. Give its identifier and the agreement it belongs to.
- If several clauses bear on the question, return each one; do not choose between them.

WHAT YOU NEVER DO
- Never compute, estimate or infer a figure. You do not have the delivery data and you \
must not reason about what the numbers might be. If a question asks for a quantity, say \
that the quantity is not yours to answer.
- Never summarise a clause away. The caller needs the words, not your reading of them.
- Never fill a gap. If the corpus is silent, say the corpus is silent and name what you \
searched for. An empty result is a finding; an invented clause is a liability.
- Never answer from general knowledge of how media contracts usually work.

OUTPUT
For each clause: the agreement, the clause identifier, the verbatim text, and one line \
saying what it governs. Nothing else."""


def build_supervisor_instructions(cfg: dict, contracts_agent: str) -> str:
    """
    The supervisor prompt. This is the demo's voice, and it is not improvised: it is
    Pattern F from Azure-Brain/Foundry-Brain/orchestration_patterns.md, an answer
    contract derived over thirteen deployed versions of this exact architecture
    (a Fabric data agent for the figures, a document corpus for the verbatims).

    Clause numbering below matches Pattern F so a future reader can diff the two.

    Note clause 6 and the test that enforces it: no figure appears anywhere in this
    prompt. A grounded agent carrying a hardcoded fact is worse than an ungrounded one,
    because it looks sourced.
    """
    fabric_agent = cfg.get("data_agent_name", "the Fabric data agent")
    return f"""\
You are Zava Media's analysis agent. You answer questions about media campaign delivery \
by combining two sources that you do not own and never second-guess.

ROUTING CONTRACT
- Delivery, spend, pacing, over- or under-delivery, invoicing gaps, any figure at all: \
call the Microsoft Fabric data agent tool. It fronts {fabric_agent}, which owns every \
metric definition in this business. It returns computed figures with the population \
they were computed over.
- Contract terms, entitlements, make-good, penalties, compensation, audit rights: call \
the {contracts_agent} agent. It returns clauses verbatim, with their identifiers.
- Most real questions need BOTH. "We over-delivered — are we owed anything?" is a figure \
from Fabric and a clause from the contracts. Call both, in the same turn.
- Call the tools. Announcing that you will call them is not calling them. Never end a \
turn having described a plan.
- One round of calls, then answer. Do not chain more than two rounds under any \
circumstances, and never call the same tool twice with the same arguments.

WHAT YOU MAY AND MAY NOT ADD
You interpret; you do not compute. Never recalculate, re-derive, re-round or \
re-aggregate a figure that came back from Fabric — relay it exactly as received, with \
the population it was measured over attached. If a figure looks wrong to you, say so \
and name the measure; do not correct it. The data semantics live in Fabric. There is \
exactly one definition of every metric in this business and it is not in this prompt.

THE ANSWER
1. Decide, never ask back. When a term has several defensible readings, name the \
criterion you used, take the widest actionable cohort, and declare that reading inside \
the answer. Never end by offering the reader a choice of interpretations.
2. Every figure keeps the scope it was measured over. A number without its population \
is not an answer.
3. State provenance in exactly one place — the trailing block described below. Nowhere else.
4. The whole reply fits on one screen, about thirty lines. When it does not, cut records \
and cut themes. Never cut the scope of a figure.
5. If a source comes back empty, say so plainly and move on. Do not retry until \
something appears, and do not fill the gap from the other source.
6. If the two sources disagree, say they disagree and show both. A contradiction between \
the delivery data and the contract is the single most valuable thing you can surface.
7. Two registers, and they never mix.
   - The prose names the population in the words the reader already uses. It carries no \
identifier of any kind: no table, column or measure name, no bracketed or backticked \
field, no DAX or GQL fragment, no comparison operators, no quoted literal value sets.
   - Every identifier goes into ONE trailing block that opens with the exact ASCII \
marker `### SOURCE` — that word, those capitals, in English, whatever language the rest \
of the answer is in. At most six lines, one fact per line: the measures used, the clause \
identifiers quoted, the filters applied. This block does not count against the thirty \
lines.
   - The plain-language description of the population is not a statement of provenance. \
Both rules survive.
8. One figure, one unit, once. A share is given as a percentage and only as a \
percentage, with the decimal tail dropped. This is the only exception to relaying \
figures exactly, and it applies to shares alone: a count, a sum or an amount keeps every \
digit. Never ask for a share under its own defining filter — if a share comes back as \
the whole population, that is the symptom, and the question must be re-asked, not \
reported.

Answer in the language the question was asked in. The `### SOURCE` marker stays English."""


# ─────────────────────────────────────────────────────────────────────────────


def _client(state):
    try:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential
    except ImportError:
        die("Missing SDK. pip install 'azure-ai-projects>=2.3.0' azure-identity\n"
            "Note the floor: >=2.0.0 is enough to CALL an agent over A2A, but >=2.3.0 "
            "is required to EXPOSE one, which this script does.")
    endpoint = state.get("foundry_endpoint")
    if not endpoint:
        die("state.json has no 'foundry_endpoint'. Run deploy_foundry_project.py first.")
    # allow_preview=True is mandatory. Both the Fabric data agent tool and the A2A tool
    # are preview surfaces; without it they are simply absent, and the resulting error
    # never uses the word "preview".
    return AIProjectClient(endpoint=endpoint,
                           credential=DefaultAzureCredential(),
                           allow_preview=True)


def upload_contracts(client, name: str) -> str:
    """Push data/contracts/*.md into a vector store for the subordinate's file_search."""
    files = sorted(CONTRACTS_DIR.glob("*.md"))
    if not files:
        die(f"No contracts found in {CONTRACTS_DIR}. Run the data generator first.")

    openai = client.get_openai_client()
    store = openai.vector_stores.create(name=name)
    print(f"    vector store {store.id}")

    file_ids = []
    for path in files:
        with open(path, "rb") as handle:
            uploaded = openai.files.create(file=handle, purpose="assistants")
        file_ids.append(uploaded.id)
        print(f"    uploaded {path.name}")

    openai.vector_stores.file_batches.create(vector_store_id=store.id, file_ids=file_ids)
    print(f"    {len(file_ids)} contracts indexed")
    return store.id


def create_contracts_agent(client, name: str, model: str, store_id: str):
    from azure.ai.projects.models import FileSearchTool, PromptAgentDefinition

    version = client.agents.create_version(
        agent_name=name,
        definition=PromptAgentDefinition(
            model=model,
            instructions=CONTRACTS_INSTRUCTIONS,
            tools=[FileSearchTool(vector_store_ids=[store_id])],
        ),
    )
    print(f"    created '{name}' (version {getattr(version, 'version', '?')})")
    return version


def enable_incoming_a2a(state, agent_name: str):
    """
    Publish the agent card and turn on the inbound protocols.

    Three traps live in this one call, all tenant-observed:

    1. An agent with `protocols: [a2a]` but NO agent card is reachable and unusable. The
       caller fails at invoke with `Failed to fetch agent card: 400`, which reads exactly
       like an RBAC fault and is not one.
    2. `agent_card` cannot be set from the Python SDK at all — this must be raw REST.
       Worse, `AgentEndpointConfig` has no `protocols` field, so round-tripping the agent
       through the SDK model silently DELETES the block, disabling `responses` and
       breaking the front door. Hence: read raw JSON, write raw JSON.
    3. Merge-patch REPLACES arrays. Every protocol must be re-listed on every write, or
       writing one turns the others off.

    And never set `agent_card_path`: Foundry resolves the card and negotiates the
    protocol version itself. Setting it is actively harmful.
    """
    endpoint = state["foundry_endpoint"]
    existing = agents_request("GET", endpoint, f"/agents/{agent_name}") or {}

    if (existing.get("agent_card") or {}).get("skills"):
        print(f"    '{agent_name}' already publishes an agent card — left untouched")
        print("    (a card may have been hand-tuned; overwriting one is destructive)")
    else:
        body = {
            "agent_card": {
                "name": agent_name,
                "description": "Returns verbatim clauses from the Zava Media contract corpus.",
                "version": "1.0.0",
                "skills": [{
                    "id": "contract_clause_lookup",
                    "name": "Contract clause lookup",
                    "description": ("Given an advertiser, a market and a subject such as "
                                    "over-delivery or penalties, returns the governing "
                                    "clauses verbatim with their identifiers."),
                    "tags": ["contracts", "media", "compliance"],
                }],
            },
            "agent_endpoint": {
                # Both protocols re-listed on purpose: merge-patch replaces arrays.
                "protocol_configuration": {"responses": {}, "a2a": {}},
            },
        }
        agents_request("PATCH", endpoint, f"/agents/{agent_name}", body)
        print(f"    published the agent card for '{agent_name}'")

    # Pin v1.0 explicitly. Foundry serves v1.0 and v0.3 on the same base path and, with
    # no version signal, serves v0.3 by design — behaviour then quietly differs from the
    # v1.0 documentation for no visible reason.
    card = agents_request("GET", endpoint,
                          f"/agents/{agent_name}/endpoint/protocols/a2a/agentCard/v1.0")
    if not card:
        die(f"The agent card for '{agent_name}' does not return. The supervisor would "
            f"fail at invoke with 'Failed to fetch agent card: 400', which looks like a "
            f"permissions problem and is not one.")
    print(f"    card verified, protocolVersion "
          f"{card.get('protocolVersion') if isinstance(card, dict) else '?'}")


def create_a2a_connection(state, conn_name: str, agent_name: str) -> str:
    """
    The caller-side connection pointing at the subordinate's A2A BASE path.

    Target must be the base path — not the card path, not the project endpoint. A
    connection whose target is the card path is created happily and never resolves.
    """
    scope = (project_scope(state["foundry_subscription_id"],
                           state["foundry_resource_group"],
                           state["foundry_account_name"],
                           state["foundry_project_name"]) + f"/connections/{conn_name}")

    if arm_get(scope):
        print(f"    connection '{conn_name}' already exists")
        return conn_name

    target = a2a_base_path(state["foundry_endpoint"], agent_name)
    arm_request("PUT", scope, {
        "properties": {
            "category": "RemoteA2A",
            "target": target,
            "authType": "AgenticIdentityToken",
            "isSharedToAll": True,
            "metadata": {"audience": "https://ai.azure.com"},
        }
    })
    print(f"    created '{conn_name}' -> {target}")
    return conn_name


def create_supervisor(client, cfg, name: str, model: str,
                      fabric_conn_id: str, a2a_conn_id: str, contracts_agent: str):
    from azure.ai.projects.models import (
        A2APreviewTool, FabricDataAgentToolParameters, MicrosoftFabricPreviewTool,
        PromptAgentDefinition, ToolProjectConnection,
    )

    tools = [
        MicrosoftFabricPreviewTool(
            fabric_dataagent_preview=FabricDataAgentToolParameters(
                project_connections=[ToolProjectConnection(project_connection_id=fabric_conn_id)]
            )
        ),
        A2APreviewTool(project_connection_id=a2a_conn_id),
    ]

    # tool_choice="required" is deliberate and only safe because the tool list is
    # homogeneous: both tools are opaque, connection-backed, and told apart by name
    # alone. `required` fixes "the supervisor called nothing and narrated a plan"; it can
    # never fix "called the wrong one". Put a self-describing tool (file_search) back on
    # this agent and `required` is satisfied by that tool every time — which is the whole
    # reason the contracts corpus lives behind A2A.
    version = client.agents.create_version(
        agent_name=name,
        definition=PromptAgentDefinition(
            model=model,
            instructions=build_supervisor_instructions(cfg, contracts_agent),
            tools=tools,
            tool_choice="required",
        ),
    )
    print(f"    created '{name}' (version {getattr(version, 'version', '?')})")
    return version


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy the Zava Media Foundry agents")
    parser.add_argument("--skip-upload", action="store_true",
                        help="reuse the vector store already in state.json")
    parser.add_argument("--delete", action="store_true", help="delete both agents")
    args = parser.parse_args()

    banner("Zava Media - Foundry agents")

    config = load_config()
    state = load_state()

    supervisor = require(config, "foundry", "orchestrator_agent_name")
    contracts = require(config, "foundry", "contracts_agent_name")
    kb_name = require(config, "foundry", "knowledge_base_name")
    fabric_conn = require(config, "foundry", "fabric_connection_name")
    a2a_conn = require(config, "foundry", "contracts_connection_name")
    model = state.get("foundry_model_deployment") or require(
        config, "foundry", "model_deployment_name")

    client = _client(state)

    if args.delete:
        for name in (supervisor, contracts):
            try:
                client.agents.delete(agent_name=name)
                print(f"    deleted '{name}'")
            except Exception as exc:  # noqa: BLE001 - absent is a fine outcome here
                print(f"    '{name}': {str(exc)[:120]}")
        for key in ("foundry_supervisor_agent", "foundry_contracts_agent",
                    "foundry_vector_store_id"):
            state.pop(key, None)
        save_state(state)
        return 0

    print_step(1, TOTAL, f"Uploading the contract corpus as '{kb_name}'")
    if args.skip_upload and state.get("foundry_vector_store_id"):
        store_id = state["foundry_vector_store_id"]
        print(f"    reusing {store_id}")
    else:
        store_id = upload_contracts(client, kb_name)
        state["foundry_vector_store_id"] = store_id
        save_state(state)

    print_step(2, TOTAL, f"Creating the subordinate '{contracts}'")
    create_contracts_agent(client, contracts, model, store_id)

    print_step(3, TOTAL, "Enabling incoming A2A on the subordinate")
    enable_incoming_a2a(state, contracts)

    print_step(4, TOTAL, f"Creating the A2A connection '{a2a_conn}'")
    create_a2a_connection(state, a2a_conn, contracts)

    print_step(5, TOTAL, "Resolving connections by name")
    # By NAME, never by GUID. This is what lets the same script promote across
    # dev/test/prod unchanged: only the connection differs.
    try:
        fabric_conn_id = client.connections.get(fabric_conn).id
        a2a_conn_id = client.connections.get(a2a_conn).id
    except Exception as exc:  # noqa: BLE001
        die(f"Could not resolve a connection by name: {exc}\n"
            f"Names are exact. Expected '{fabric_conn}' and '{a2a_conn}'.")
    print(f"    {fabric_conn} -> {fabric_conn_id}")
    print(f"    {a2a_conn} -> {a2a_conn_id}")

    print_step(6, TOTAL, f"Creating the supervisor '{supervisor}'")
    create_supervisor(client, config, supervisor, model,
                      fabric_conn_id, a2a_conn_id, contracts)

    print_step(7, TOTAL, "Saving state")
    state["foundry_supervisor_agent"] = supervisor
    state["foundry_contracts_agent"] = contracts
    save_state(state)

    print(f"""
Both agents are deployed. TWO THINGS MUST HAPPEN BEFORE THE DEMO.

1. APPROVE THE TOOLS, one agent at a time, in the playground.
   Tool approval cannot be completed inside a workflow or a multi-agent run: the run
   errors instead, with no useful message. Open '{supervisor}' alone, ask something
   that forces each tool to fire, and choose "Always approve this tool".

2. VERIFY ROUTING BY CONNECTION NAME, not by tool type.
   Ask a purely quantitative question and confirm the Fabric tool fired AND the
   contracts agent did not. Both A2A subordinates emit the same item type, so the type
   alone proves nothing — a check written on it passes happily while the supervisor is
   asking the contract corpus for a number.

Then: python verify_foundry.py
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
