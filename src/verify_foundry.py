"""
Step 14 — prove the chain, do not sample it.

This script exists because of a specific, documented trap: every A2A subordinate emits
the SAME item type (`a2a_preview_call`), so the type no longer identifies which one ran.
A check written on the type alone passes happily while the supervisor is quietly asking
the contract corpus for a number — which is precisely the failure this architecture was
shaped to avoid. Routing is therefore asserted by NAME, and always as a pair: the tool
that should have fired did, AND the other one did not.

Three probes, each isolating one claim:

    quantitative  a figure question       -> Fabric fired, contracts did NOT
    contractual   a clause question       -> contracts fired
    the demo      the question we present -> BOTH fired

Then the answer contract is checked structurally, because prose rules do not hold and
"it looked fine on stage" is not a measurement.

Usage:
    python verify_foundry.py
    python verify_foundry.py --question "..."     # ad-hoc, prints the trace
"""

import argparse
import json
import re
import sys

from platform_env import bootstrap
bootstrap()

from helpers import load_config, load_state, print_step
from foundry_common import banner, die, foundry_credential, require

SOURCE_MARKER = "### SOURCE"
MAX_PROSE_LINES = 30

# The MCP endpoint answers 404 when the capacity behind the workspace is paused. Not 503,
# not 409 — 404, with the reason buried in a JSON-RPC error body that the Foundry service
# does not surface. Read the body before believing the status line.
CAPACITY_PAUSED_MARKER = "CapacityNotActive"


def fabric_tool_name(config: dict) -> str:
    """The name the Fabric tool fires under — which is NOT the connection name.

    This changes with the binding, and getting it wrong makes a passing chain look broken:

        MicrosoftFabricPreviewTool  -> the tool is named after the CONNECTION
        FabricIQPreviewTool         -> the tool is named by the MCP server, i.e.
                                       `DataAgent_<data agent name>` from tools/list

    We are on the second one. Asserting the connection name here reported `never fired`
    while the trace plainly showed the call — the assertion was stale, not the chain.
    """
    agent_name = config.get("data_agent_name", "")
    return f"DataAgent_{agent_name}" if agent_name else "DataAgent_"


def preflight_capacity(state) -> None:
    """Fail loudly, and for the right reason, when the Fabric capacity is paused.

    This exists because of a genuinely expensive afternoon. A paused capacity makes the
    data agent's MCP endpoint answer:

        HTTP 404  {"error":{"code":-32601,"message":"Internal error CapacityNotActive..."}}

    and Foundry reports only its own summary of that — `returned HTTP 404 (Not Found)
    while enumerating tools`. A 404 on a URL reads as "wrong route", so the investigation
    goes to routing, then RBAC, then tenant settings, then four different `authType`
    values — all of which fail identically, because none of them was ever the cause.

    One request, sent before the probes, replaces all of it.
    """
    url = state.get("fabric_mcp_server_url")
    if not url:
        return
    try:
        import requests
        from azure.identity import DefaultAzureCredential
        token = DefaultAzureCredential().get_token(
            "https://api.fabric.microsoft.com/.default").token
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}",
                     # BOTH types. With only application/json this surface returns a
                     # misleading 500 on some routes — see mcp_ontology.md.
                     "Accept": "application/json, text/event-stream",
                     "Content-Type": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                             "clientInfo": {"name": "verify", "version": "1"}}},
            timeout=90)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! could not pre-check the Fabric MCP endpoint ({str(exc)[:120]})")
        print("    continuing — but if the probes fail on a 404, check this first")
        return

    if CAPACITY_PAUSED_MARKER in (resp.text or ""):
        die("The Fabric capacity behind this workspace is PAUSED.\n\n"
            "  The data agent's MCP endpoint answers HTTP 404 for a paused capacity, and\n"
            "  Foundry relays that as '404 (Not Found) while enumerating tools'. Nothing\n"
            "  is wrong with the connection, the route, the RBAC or the authType.\n\n"
            "  Resume it, wait for state=Active, then re-run:\n"
            "    az fabric capacity resume -g <rg> --capacity-name <name>\n"
            "    az resource show -g <rg> -n <name> "
            "--resource-type Microsoft.Fabric/capacities --query properties.state -o tsv\n\n"
            "  The first call after a resume can still exceed the service's 100 s tool\n"
            "  timeout while the capacity warms up. A second run usually passes.")

    if resp.status_code == 200:
        print("  Fabric MCP endpoint reachable, capacity active.")
    else:
        print(f"  ! Fabric MCP endpoint returned {resp.status_code} — "
              f"{(resp.text or '')[:160]}")

# Identifiers must never appear in the prose half. Deliberately broad: the failure mode
# is an answer that is entirely true, entirely sourced, and unreadable to the media
# planner it was written for.
IDENTIFIER_PATTERNS = [
    (r"\[[A-Za-z_][A-Za-z0-9 _]*\]", "a bracketed field or measure"),
    (r"`[^`]+`", "a backticked identifier"),
    (r"\b(?:dim|fact)_[a-z_]+\b", "a table name"),
    (r"\bIN\s*\{", "a literal value set"),
    (r"(?<![<>=!])>=|<=(?!=)", "a comparison operator"),
]


def _client(state):
    try:
        from azure.ai.projects import AIProjectClient
    except ImportError:
        die("pip install 'azure-ai-projects>=2.0.0' azure-identity")
    endpoint = state.get("foundry_endpoint")
    if not endpoint:
        die("state.json has no 'foundry_endpoint'. Run deploy_foundry_project.py first.")
    return AIProjectClient(endpoint=endpoint,
                           credential=foundry_credential(),
                           allow_preview=True)


def ask(client, agent_name: str, question: str):
    """
    One turn against the supervisor. Returns (answer_text, tool_names_that_fired).

    Only the supervisor's own hops are visible here. Whatever happens INSIDE a
    subordinate arrives all at once with its output — so this function can prove that
    the contracts agent was called, and can say nothing about what it did internally.
    """
    openai = client.get_openai_client()
    response = openai.responses.create(
        input=question,
        # `type` is REQUIRED and its only legal value is the literal "agent_reference".
        # Omitting it fails with `Required property 'type' is missing`, param
        # `agent_reference.type` — which reads like the SDK forgot a field rather than
        # like our payload is short one. Azure-Brain documented this call shape without
        # the discriminator and marked the line "doc, never run"; that honesty is what
        # made this cheap to find. Verified live 2026-09-02: the service answers
        # `const: Expected "agent_reference"` to any other value, so it enumerates
        # itself if you send a deliberately wrong one.
        extra_body={"agent_reference": {"type": "agent_reference", "name": agent_name}},
    )

    fired = []
    for item in (getattr(response, "output", None) or []):
        kind = getattr(item, "type", "") or ""
        if "call" not in kind:
            continue
        # By NAME. The type is the same for every A2A subordinate and proves nothing.
        name = (getattr(item, "name", None)
                or getattr(item, "server_label", None)
                or getattr(item, "connection_name", None)
                or kind)
        fired.append(str(name))

    text = getattr(response, "output_text", None)
    if not text:
        chunks = []
        for item in (getattr(response, "output", None) or []):
            for part in (getattr(item, "content", None) or []):
                if getattr(part, "text", None):
                    chunks.append(part.text)
        text = "\n".join(chunks)
    return text or "", fired


def matched(fired, needle: str) -> bool:
    needle = needle.lower()
    return any(needle in name.lower() for name in fired)


def check_answer_contract(text: str) -> list:
    """
    Structural checks on the answer. Returns a list of failures, empty if clean.

    These are the clauses that prose could not enforce on their own — hence a test.
    """
    problems = []

    occurrences = text.count(SOURCE_MARKER)
    if occurrences == 0:
        problems.append(f"no '{SOURCE_MARKER}' block — provenance has nowhere to live, "
                        f"so it will leak into the prose")
        return problems
    if occurrences > 1:
        problems.append(f"'{SOURCE_MARKER}' appears {occurrences} times — two locations "
                        f"are read as two presentations, and both get filled")

    prose, _, source_block = text.partition(SOURCE_MARKER)

    prose_lines = [ln for ln in prose.strip().splitlines() if ln.strip()]
    if len(prose_lines) > MAX_PROSE_LINES:
        problems.append(f"{len(prose_lines)} lines of prose, limit is {MAX_PROSE_LINES} "
                        f"(the SOURCE block is excluded on purpose)")

    for pattern, what in IDENTIFIER_PATTERNS:
        hit = re.search(pattern, prose)
        if hit:
            problems.append(f"prose contains {what}: {hit.group(0)!r} — identifiers "
                            f"belong in the SOURCE block only")

    source_lines = [ln for ln in source_block.strip().splitlines() if ln.strip()]
    if len(source_lines) > 6:
        problems.append(f"SOURCE block has {len(source_lines)} lines, limit is 6")

    # Clause 8: a share printed twice, once as a ratio and once as a percentage.
    if re.search(r"0[.,]\d{6,}", prose):
        problems.append("a full-precision ratio is printed — give the percentage only, "
                        "and drop the decimal tail")

    return problems


def probe(client, agent, label, question, expect, forbid=None) -> bool:
    print(f"\n  {label}")
    print(f"    Q: {question}")
    try:
        text, fired = ask(client, agent, question)
    except Exception as exc:  # noqa: BLE001
        print(f"    FAILED to run: {str(exc)[:400]}")
        if "approval" in str(exc).lower():
            print("    -> a tool is waiting on an approval. Open the agent alone in the")
            print("       playground, force each tool to fire, and 'Always approve'.")
        return False

    print(f"    tools fired: {fired or '(none)'}")
    ok = True

    for needle in expect:
        if matched(fired, needle):
            print(f"    OK   '{needle}' fired")
        else:
            print(f"    FAIL '{needle}' never fired")
            ok = False

    for needle in (forbid or []):
        if matched(fired, needle):
            print(f"    FAIL '{needle}' fired and should not have — the supervisor "
                  f"answered from the wrong source")
            ok = False
        else:
            print(f"    OK   '{needle}' stayed out of it")

    problems = check_answer_contract(text)
    for problem in problems:
        print(f"    FAIL answer contract: {problem}")
    ok = ok and not problems

    print("    ---- answer ----")
    for line in text.strip().splitlines():
        print(f"    | {line}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Zava Media Foundry chain")
    parser.add_argument("--question", help="ask one ad-hoc question and print the trace")
    args = parser.parse_args()

    banner("Zava Media - verifying the Foundry chain")

    config = load_config()
    state = load_state()
    agent = state.get("foundry_supervisor_agent") or require(
        config, "foundry", "orchestrator_agent_name")
    contracts = state.get("foundry_contracts_agent") or require(
        config, "foundry", "contracts_agent_name")
    # Called for its validation side effect only: the connection name is no longer what
    # the Fabric tool fires under, but a config missing it still cannot deploy.
    require(config, "foundry", "fabric_connection_name")
    a2a_conn = require(config, "foundry", "contracts_connection_name")
    # The Fabric tool does NOT fire under the connection name on this binding.
    fabric_tool = fabric_tool_name(config)

    client = _client(state)

    if args.question:
        text, fired = ask(client, agent, args.question)
        print(f"\ntools fired: {fired}\n")
        print(text)
        problems = check_answer_contract(text)
        for problem in problems:
            print(f"\nanswer contract: {problem}")
        return 0 if not problems else 1

    advertiser = config.get("demo_question_advertiser", "the advertiser")
    market = config.get("demo_question_market", "the market")
    quarter = config.get("demo_question_quarter", "the quarter")

    results = []

    preflight_capacity(state)

    print_step(1, 3, "Quantitative — Fabric must answer, contracts must stay out")
    results.append(probe(
        client, agent, "figure only",
        f"For advertiser {advertiser} in market {market}, how did delivered impressions "
        f"compare with the plan in {quarter}?",
        expect=[fabric_tool], forbid=[a2a_conn, contracts],
    ))

    print_step(2, 3, "Contractual — the contracts agent must answer")
    results.append(probe(
        client, agent, "clause only",
        f"What does our agreement with advertiser {advertiser} say about over-delivery "
        f"and make-good?",
        expect=[a2a_conn], forbid=[],
    ))

    print_step(3, 3, "The demo question — both sources, one answer")
    results.append(probe(
        client, agent, "the demo",
        f"On {quarter} for advertiser {advertiser} in market {market} we over-delivered. "
        f"Does the contract provide for compensation?",
        expect=[fabric_tool, a2a_conn], forbid=[],
    ))

    print("\n" + "=" * 66)
    if all(results):
        print("PASS - all three probes routed correctly and the answers hold their shape.")
        return 0

    print("FAIL - see above.")
    print("""
Ordered checklist. Work down it; do not skip.

  1. Were the tools approved? A run waiting on an approval fails with no useful
     message. Open the supervisor alone in the playground and approve each tool.
  2. 'Failed to fetch agent card: 404' -> SUSPECT RBAC FIRST, not the URL. A missing
     'Foundry Agent Consumer' grant reports as 404 for several minutes before it ever
     reports as 403. Observed progression: 404, 404, 404, 403, 200 over ~4 minutes.
     Grant it to the caller's instance_identity.principal_id (NOT blueprint's, which
     is not assignable) and retry for at least 5 minutes before touching anything else.
  3. Is incoming A2A enabled on the subordinate, WITH a published card? A missing card
     gives 'Failed to fetch agent card: 400' — a 400, note, not the 404 of item 2.
  4. 'Failed to fetch agentic identity access token ... response: ' with an EMPTY
     response means no token was minted: the connection needs `properties.audience`
     = 'https://ai.azure.com' as a first-class field. Setting it only inside
     `properties.metadata` is stored and ignored.
  5. Does the A2A connection target the BASE path — not the card path, not the project
     endpoint?
  6. 'returned HTTP 404 (Not Found) while enumerating tools' -> CHECK THE CAPACITY, not
     the route. A paused Fabric capacity makes the data agent's MCP endpoint answer 404
     with 'CapacityNotActive' in the body, and Foundry relays only the status. The
     preflight above catches this now; if you got here anyway, resume the capacity and
     retry. Do not touch the connection, the RBAC or the authType — four different
     authTypes were tried against a paused capacity and all four failed identically.
  7. Fabric tool 'never fired' while the trace clearly shows it? The expected NAME is
     wrong, not the chain. FabricIQPreviewTool fires as `DataAgent_<data agent name>`
     (the MCP server's own tool name); only MicrosoftFabricPreviewTool fires under the
     connection name. See fabric_tool_name().
  8. 'TaskCanceledException ... HttpClient.Timeout of 100 seconds' is a cold capacity,
     not a broken tool. It is common on the first call after a resume. Re-run.
  9. If the contracts agent answered a purely quantitative question: the tool list has
     stopped being homogeneous. Something self-describing is attached to the supervisor
     and is out-competing the connection-backed tools. Remove it.
 10. If the supervisor called nothing and narrated a plan instead: tool_choice is not
     'required'.
""")
    return 1


if __name__ == "__main__":
    sys.exit(main())
