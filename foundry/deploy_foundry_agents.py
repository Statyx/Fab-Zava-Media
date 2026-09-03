"""
Step 13 — the two Foundry agents.

    Zava-Media-Contracts   subordinate. Owns the contract corpus. Reached over A2A.
    Zava-Media-Agent       supervisor. Owns routing and the answer. Reached by the user.

WHY THE SUBORDINATE EXISTS AT ALL
---------------------------------
The obvious design is one supervisor holding the Fabric data agent tool AND a
`file_search` over design/contracts/. That design is documented to fail on a live tenant,
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
    python -m foundry.deploy_foundry_agents
    python -m foundry.deploy_foundry_agents --skip-upload      # corpus unchanged
    python -m foundry.deploy_foundry_agents --delete
"""

import argparse
import json
import sys
from pathlib import Path

from fabric._shared.platform_env import bootstrap
bootstrap()

from fabric._shared.helpers import load_config, load_state, save_state, print_step
from fabric._shared.paths import CONTRACTS as CONTRACTS_DIR
from foundry.foundry_common import (
    AzError, _az, a2a_base_path, agents_request, arm_get, arm_request, banner,
    check_agent_name, die, foundry_credential, project_scope, require,
)

TOTAL = 8

# The audience the A2A runtime mints the caller's token for. Must be set as a first-class
# connection property; `metadata.audience` alone is stored and ignored.
A2A_AUDIENCE = "https://ai.azure.com"

# Least-privilege role for an agent that only calls another agent.
AGENT_CONSUMER_ROLE = "Foundry Agent Consumer"


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
                           credential=foundry_credential(),
                           allow_preview=True)


def upload_contracts(client, name: str, existing_id: str = "") -> str:
    """Push design/contracts/*.md into a vector store for the subordinate's file_search.

    Reuses `existing_id` when it still resolves. This step is the expensive one - a
    store plus five file uploads - and it is also the one that runs before the agent
    names are exercised against the service, so a failure further down the chain used to
    leave a fresh billable store behind on every retry. `--skip-upload` existed for this,
    but the orchestrator cannot pass flags to a step (it neutralises argv on purpose), so
    the reuse path was unreachable from `deploy_all.py` - the only way this script is
    normally run. Reuse is therefore the default, and `--force-upload` overrides it.
    """
    if existing_id:
        try:
            client.get_openai_client().vector_stores.retrieve(existing_id)
            print(f"    reusing vector store {existing_id}")
            return existing_id
        except Exception:  # noqa: BLE001 - stale id in state is a fine reason to rebuild
            print(f"    vector store {existing_id} no longer resolves, rebuilding")

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

    # The card carries NO top-level `protocolVersion`. Versions live one level down, one
    # per entry of `supportedInterfaces`. Reading the top level printed a confident
    # "protocolVersion None" on a perfectly valid card — a check that cannot fail is worse
    # than no check, because it is quoted later as evidence.
    versions = sorted({(i or {}).get("protocolVersion")
                       for i in (card.get("supportedInterfaces") or [])
                       if isinstance(i, dict)} - {None})
    if "1.0" not in versions:
        die(f"The card for '{agent_name}' does not advertise protocolVersion 1.0 "
            f"(got {versions or 'none'}).")
    print(f"    card verified, protocolVersion(s) {', '.join(versions)}")


def create_a2a_connection(state, conn_name: str, agent_name: str) -> str:
    """
    The caller-side connection pointing at the subordinate's A2A BASE path.

    Target must be the base path — not the card path, not the project endpoint. A
    connection whose target is the card path is created happily and never resolves.

    `audience` must be set as a FIRST-CLASS property. Putting it only in `metadata`
    (which mirrors how the portal displays it) is accepted by ARM and stored, and then
    the runtime cannot mint the caller's token:

        Failed to fetch agentic identity access token with status code: 400, response: .

    The empty `response:` is the tell — there is no downstream call to report on, because
    the token was never issued. Tenant-verified 2026-09-02: with `properties.audience`
    set, that error is replaced by the *next* one in the chain; with it unset or wrong,
    it comes straight back.
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
            "audience": A2A_AUDIENCE,          # the one the runtime actually reads
            "isSharedToAll": True,
            "metadata": {"audience": A2A_AUDIENCE},
        }
    })
    print(f"    created '{conn_name}' -> {target}")
    return conn_name


def grant_agent_consumer(state, agent_name: str) -> None:
    """
    Give the CALLER agent rights on the project that hosts the callee.

    Without this the card fetch fails and — this is the expensive part — it fails as
    **404 Not Found**, not 403. A 404 sends you hunting for a wrong URL; the URL is fine.
    Tenant-verified 2026-09-02, the progression while the assignment propagated was:

        404 · 404 · 404 · 403 · 200        (~4 minutes, one attempt per minute)

    So treat 404 on the agent card as "RBAC has not landed yet" until proven otherwise,
    and only then suspect the path.

    An agent document exposes TWO principal ids and only one of them is assignable:
      - `instance_identity.principal_id`  -> works
      - `blueprint.principal_id`          -> rejected, PrincipalTypeNotSupported
        ("Principals of type #microsoft.graph.agentIdentityBlueprintPrincipal cannot
         validly be used in role assignments")
    """
    doc = agents_request("GET", state["foundry_endpoint"], f"/agents/{agent_name}") or {}
    principal = ((doc.get("instance_identity") or {}).get("principal_id") or "").strip()
    if not principal:
        die(f"'{agent_name}' exposes no instance_identity.principal_id, so the A2A hop "
            f"cannot be authorised. The agent was probably not created successfully.")

    scope = project_scope(state["foundry_subscription_id"], state["foundry_resource_group"],
                          state["foundry_account_name"], state["foundry_project_name"])
    # project_scope() returns a full https://management.azure.com/... URL because it feeds
    # arm_request(). `az role assignment --scope` wants a BARE resource id, and rejects the
    # URL form with (MissingSubscription) — an error that points at the account context,
    # which is correctly set, rather than at the argument that is actually malformed.
    scope = "/" + scope.split("://", 1)[-1].split("/", 1)[-1] if "://" in scope else scope
    try:
        # --subscription is explicit on purpose: the CLI resolves the call against its own
        # default rather than the scope, so a standalone run must not rely on deploy_all.py
        # having set it first.
        _az(["role", "assignment", "create",
             "--assignee-object-id", principal,
             "--assignee-principal-type", "ServicePrincipal",
             "--role", AGENT_CONSUMER_ROLE, "--scope", scope,
             "--subscription", state["foundry_subscription_id"]])
        print(f"    granted '{AGENT_CONSUMER_ROLE}' to {agent_name} ({principal})")
    except AzError as exc:
        if "RoleAssignmentExists" in str(exc):
            print(f"    '{AGENT_CONSUMER_ROLE}' already granted to {agent_name}")
        else:
            raise
    print("    NOTE: role assignments take minutes to propagate. Until they do, the "
          "agent card returns 404 — that is expected, not a wrong URL.")


def create_supervisor(client, cfg, name: str, model: str,
                      fabric_conn_id: str, a2a_conn_id: str, contracts_agent: str,
                      fabric_server_url: str):
    from azure.ai.projects.models import (
        A2APreviewTool, FabricIQPreviewTool, PromptAgentDefinition,
    )

    fnd = cfg.get("foundry", {}) or {}

    # WHY FabricIQPreviewTool AND NOT MicrosoftFabricPreviewTool
    #   MicrosoftFabricPreviewTool resolves a CustomKeys connection of category
    #   `AzureFabric`, which ARM cannot create at any api-version — that binding is
    #   portal-only, and this repo used to stop there and print manual steps.
    #   FabricIQPreviewTool reaches the SAME published data agent over its MCP endpoint
    #   through a RemoteTool/GenericProtocol connection, which ARM creates happily. The
    #   whole chain is scriptable again.
    #
    # WHAT IT COSTS
    #   The data agent's own instructions do NOT travel over MCP. Its metric definitions
    #   and populations stay behind, so build_supervisor_instructions() carries the guard
    #   rails instead. Do not thin them out.
    #
    # require_approval
    #   Defaults to "always": every call pauses the run for a human approval that an
    #   unattended verify/replay has nowhere to answer, so the run simply hangs. Set
    #   explicitly here so the posture is a recorded decision, not an unread default.
    # ENDPOINT SOURCE — two modes, and they fail differently.
    #   "connection" (default): server_url is NOT sent; the connection's `target` carries
    #       the endpoint. This is what a portal-made connection expects.
    #   "explicit": server_url is sent alongside. It documents WHICH Fabric item is meant,
    #       but the service resolves it itself and answered 404 on a URL that a direct
    #       probe with a user token serves happily — so it is not a superset of "connection".
    # Live 2026-09-03: "explicit" -> 400/"returned HTTP 404 while enumerating tools".
    endpoint_source = str(fnd.get("fabric_iq_endpoint", "connection")).strip().lower()

    iq_kwargs = {
        "project_connection_id": fabric_conn_id,
        "server_label": str(fnd.get("fabric_iq_server_label", "fabricdataagent")),
        "require_approval": str(fnd.get("require_approval", "never")).strip().lower(),
    }
    if endpoint_source == "explicit":
        iq_kwargs["server_url"] = fabric_server_url

    tools = [
        FabricIQPreviewTool(**iq_kwargs),
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
    parser.add_argument("--force-upload", action="store_true",
                        help="rebuild the vector store even when state.json has one")
    parser.add_argument("--delete", action="store_true", help="delete both agents")
    args = parser.parse_args()

    banner("Zava Media - Foundry agents")

    config = load_config()
    state = load_state()

    # Validated BEFORE the client is built, and long before the corpus is uploaded.
    # The service rejects an illegal name at step 2 of 7, i.e. after step 1 has already
    # created a vector store and pushed five files into it.
    supervisor = check_agent_name(
        require(config, "foundry", "orchestrator_agent_name"),
        "foundry.orchestrator_agent_name")
    contracts = check_agent_name(
        require(config, "foundry", "contracts_agent_name"),
        "foundry.contracts_agent_name")
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
    store_id = upload_contracts(
        client, kb_name,
        existing_id="" if args.force_upload else state.get("foundry_vector_store_id", ""))
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
    # The MCP endpoint is written to state by deploy_foundry_connection.py. Recomputing it
    # here would let the two drift; if it is missing, that step has not run.
    fabric_server_url = state.get("fabric_mcp_server_url")
    if not fabric_server_url:
        die("state.json has no 'fabric_mcp_server_url'.\n"
            "Run deploy_foundry_connection.py first — it creates the RemoteTool connection "
            "and records the data agent's MCP endpoint that the tool needs.")
    create_supervisor(client, config, supervisor, model,
                      fabric_conn_id, a2a_conn_id, contracts, fabric_server_url)

    print_step(7, TOTAL, f"Granting '{AGENT_CONSUMER_ROLE}' to the supervisor")
    # Must run AFTER create_supervisor: the identity we grant to is minted with the agent.
    grant_agent_consumer(state, supervisor)

    print_step(8, TOTAL, "Saving state")
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

Then: python -m foundry.verify_foundry
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
