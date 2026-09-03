"""
Tests for the Foundry half of the chain.

Every test here corresponds to a failure that has actually been observed on a tenant and
is recorded in Azure-Brain/Foundry-Brain. None of them needs a tenant to run: they assert
on the shape of what we are about to deploy, which is the only moment these mistakes are
still cheap.

The expensive property of the Foundry failures is that they all deploy CLEANLY. A
supervisor that never calls Fabric, an A2A target pointing at the wrong path, a missing
agent card — each one is a green deploy followed by a demo that answers fluently out of
the wrong source. Nothing downstream notices.
"""

import ast
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
FOUNDRY = ROOT / "foundry"
sys.path.insert(0, str(ROOT))

FOUNDRY_SCRIPTS = [
    "foundry_common.py",
    "deploy_foundry_project.py",
    "deploy_foundry_connection.py",
    "deploy_foundry_agents.py",
    "verify_foundry.py",
]


def source(name: str) -> str:
    return (FOUNDRY / name).read_text(encoding="utf-8")


def code_only(name: str) -> str:
    """
    Source with comments and string literals removed.

    These files document the traps they avoid, so a naive grep for a forbidden token
    finds the paragraph warning against it. Strip anything that is not executed.
    """
    import io
    import tokenize
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(source(name)).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


def tree(name: str) -> ast.Module:
    return ast.parse(source(name))


@pytest.fixture(scope="module")
def agents_mod():
    """
    deploy_foundry_agents without importing the Azure SDK.

    The SDK imports live inside the functions precisely so the prompts can be inspected
    offline — which is what makes the contract testable in CI.
    """
    import importlib
    return importlib.import_module("foundry.deploy_foundry_agents")


@pytest.fixture(scope="module")
def config():
    return yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def supervisor_prompt(agents_mod, config):
    return agents_mod.build_supervisor_instructions(
        config, config["foundry"]["contracts_agent_name"])


# ── The documented tool-selection failure ────────────────────────────────────

def test_supervisor_has_no_self_describing_tool(agents_mod):
    """
    The one that kills this demo.

    A supervisor holding a connection-backed tool AND a `file_search` never calls the
    connection: file_search describes its own purpose to the model, a connection tool
    surfaces only under its name. Three isolating runs on a live tenant, and
    tool_choice="required" did not rescue it — the model met the constraint with the
    wrong tool.

    So: FileSearchTool may appear in this module (the SUBORDINATE needs it) but must
    never be built inside create_supervisor.
    """
    fn = next(n for n in ast.walk(tree("deploy_foundry_agents.py"))
              if isinstance(n, ast.FunctionDef) and n.name == "create_supervisor")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "FileSearchTool" not in called, (
        "FileSearchTool is attached to the supervisor. The Fabric tool will never fire "
        "and every question will be answered out of the contracts corpus."
    )


def test_supervisor_tools_are_all_connection_backed(agents_mod):
    """
    tool_choice='required' is only safe on a homogeneous tool list. It forces *a* call,
    never the *right* one. Both supervisor tools must be opaque and connection-backed so
    that the model can only tell them apart by name.

    The Fabric half may be bound either way — both are connection-backed, which is the
    property this test actually defends:

        MicrosoftFabricPreviewTool  CustomKeys/AzureFabric  ... portal-created only
        FabricIQPreviewTool         RemoteTool/GenericProtocol ... created from ARM

    We use the second one, so the whole chain deploys without a portal step. Pinning the
    first one by name made this test fail on a working supervisor — the assertion was
    stale, not the code. Assert the *shape* (exactly two, both connection-backed), and
    let the Fabric binding vary.
    """
    fabric_tools = {"MicrosoftFabricPreviewTool", "FabricIQPreviewTool"}
    fn = next(n for n in ast.walk(tree("deploy_foundry_agents.py"))
              if isinstance(n, ast.FunctionDef) and n.name == "create_supervisor")
    tool_ctors = {n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id.endswith("Tool")}
    assert len(tool_ctors & fabric_tools) == 1, (
        f"supervisor tool set is {tool_ctors}; expected exactly one Fabric binding "
        f"out of {sorted(fabric_tools)}"
    )
    assert tool_ctors - fabric_tools == {"A2APreviewTool"}, (
        f"supervisor tool set is {tool_ctors}; besides the Fabric binding it must carry "
        f"A2APreviewTool and nothing else — a self-describing tool out-competes the "
        f"connection-backed ones under tool_choice='required'"
    )


def test_supervisor_forces_a_tool_call(agents_mod):
    """
    Without tool_choice='required' the supervisor can end a turn having called nothing,
    narrating the routing rule as a plan. The client renders that as a one-line unsourced
    answer. A prose rule against it does not hold; this does.
    """
    assert re.search(r'tool_choice\s*=\s*["\']required["\']',
                     source("deploy_foundry_agents.py")), \
        "tool_choice='required' is missing from the supervisor definition"


# ── Pattern F: the answer contract ───────────────────────────────────────────

def _planted_figures(text: str) -> list[str]:
    """Numeric tokens in `text`, ignoring the contract's own clause numbering."""
    stripped = re.sub(r"^\s*\d+\.", "", text, flags=re.MULTILINE)
    return [d.strip() for d in re.findall(r"(?<![\w.])\d[\d\s.,]*(?![\w])", stripped)
            if d.strip() not in {"", "."}]


def test_supervisor_prompt_carries_no_figure(supervisor_prompt):
    """
    Clause 6. A grounded agent with a hardcoded fact is worse than an ungrounded one,
    because it looks sourced. The observed instance of this failure hardcoded ten product
    IDs as 'at risk' in a prompt that also said 'only from the tool output'.

    Clause numbers (1., 2., ...) are the contract's own structure, not data. Line budgets
    are spelled out in words for the same reason.

    The second assertion is a mutation check: a detector that cannot fail is not a test,
    and this one is deliberately lenient about clause numbering.
    """
    assert not _planted_figures(supervisor_prompt), \
        f"the supervisor prompt carries figures: {_planted_figures(supervisor_prompt)}"
    assert _planted_figures(supervisor_prompt + "\nBudget was 4.2 M EUR."), \
        "the figure detector does not detect figures"


def test_source_marker_is_identical_in_prompt_and_verifier(supervisor_prompt):
    """
    The prompt mandates a marker; the verifier splits on it. If the two drift, a
    perfectly correct answer fails verification and someone 'fixes' the agent.
    """
    from foundry import verify_foundry
    assert verify_foundry.SOURCE_MARKER in supervisor_prompt, (
        f"the verifier splits on {verify_foundry.SOURCE_MARKER!r} but the prompt does "
        f"not mandate that exact literal"
    )


def test_supervisor_states_when_to_call_each_tool(supervisor_prompt, config):
    """
    Rule 6: for every tool, the instructions must say WHEN to call it and WHAT it
    returns. Vague delegation looks like a hallucination but is a missing contract.
    """
    lowered = supervisor_prompt.lower()
    assert "fabric" in lowered
    assert config["foundry"]["contracts_agent_name"] in supervisor_prompt
    for phrase in ("it returns", "call both"):
        assert phrase in lowered, f"the routing contract never says {phrase!r}"


def test_supervisor_bounds_the_loop(supervisor_prompt):
    """
    A supervisor that calls agents which can call agents needs an explicit depth and turn
    limit written into its instructions. Nothing enforces this for you.
    """
    lowered = supervisor_prompt.lower()
    assert "do not chain more than two rounds" in lowered, "no turn bound in the prompt"
    assert "same tool twice" in lowered, "nothing forbids re-calling a tool identically"


def test_supervisor_relays_figures_rather_than_recomputing(supervisor_prompt):
    """
    Clause 2 and the boundary rule. The data semantics stay on the data side; Foundry
    never reimplements a measure. Left free, a supervisor rounds '825 customers (High +
    Critical)' into '800 customers', reintroducing one storey up the ambiguity the data
    layer just resolved.
    """
    lowered = supervisor_prompt.lower()
    assert "never recalculate" in lowered or "do not recalculate" in lowered
    assert "interpret; you do not compute" in lowered


def test_supervisor_splits_the_two_registers(supervisor_prompt):
    """
    Clause 7. The prose names the population in the reader's words and carries no
    identifier; identifiers go to one trailing block. Without this the answer is every
    word true, sourced, and unreadable to the media planner it was written for.
    """
    lowered = supervisor_prompt.lower()
    assert "no identifier of any kind" in lowered
    assert "does not count against" in lowered, \
        "the SOURCE block must be excluded from the line budget, or it competes with " \
        "the answer for room"


# ── The subordinate ──────────────────────────────────────────────────────────

def test_contracts_agent_refuses_to_produce_figures(agents_mod):
    """
    The mirror of the Fabric agent's own boundary. Each side must refuse the other's
    half, or the demo's whole claim — number from Fabric, clause from the corpus —
    stops being structurally true.
    """
    text = agents_mod.CONTRACTS_INSTRUCTIONS.lower()
    assert "never compute" in text
    assert "not yours to answer" in text
    assert "never fill a gap" in text or "corpus is silent" in text


def test_contracts_agent_returns_clauses_verbatim(agents_mod):
    text = agents_mod.CONTRACTS_INSTRUCTIONS.lower()
    assert "verbatim" in text
    assert "never summarise" in text or "never summarize" in text


# ── A2A wiring ───────────────────────────────────────────────────────────────

def test_a2a_target_is_the_base_path_not_the_card():
    """
    The connection target must be the A2A BASE path. Pointed at the card path or the
    project endpoint it is created happily — a connection is not validated at creation —
    and never resolves at invoke.
    """
    from foundry import foundry_common
    path = foundry_common.a2a_base_path(
        "https://<resource>.services.ai.azure.com/api/projects/p", "Some_Agent")
    assert path.endswith("/agents/Some_Agent/endpoint/protocols/a2a")
    assert "agentCard" not in path


def test_agent_card_path_is_never_set():
    """
    Foundry resolves the card and negotiates the protocol version itself. Setting
    agent_card_path is actively harmful — tenant-observed.
    """
    for name in FOUNDRY_SCRIPTS:
        assert "agent_card_path" not in code_only(name), \
            f"{name} sets agent_card_path, which breaks protocol negotiation"


def test_the_card_is_published_and_verified(agents_mod):
    """
    An agent with protocols:[a2a] but no card is reachable and unusable: the caller fails
    with 'Failed to fetch agent card: 400', which reads exactly like an RBAC fault.
    So the deploy must write a card AND read it back.
    """
    text = source("deploy_foundry_agents.py")
    assert "agent_card" in text, "no agent card is published"
    assert "agentCard/v1.0" in text, (
        "the card is never read back. Foundry serves v1.0 and v0.3 on the same base "
        "path and defaults to v0.3 when given no version signal."
    )


def test_the_audience_is_a_first_class_connection_property():
    """
    Tenant-verified: `properties.audience` is what the runtime reads to mint the caller's
    token. Writing the value only into `properties.metadata.audience` — which is how the
    portal displays it — is accepted by ARM, stored, and ignored, and the hop then fails
    with 'Failed to fetch agentic identity access token with status code: 400, response: '
    whose EMPTY response body is the tell that no downstream call ever happened.
    """
    text = source("deploy_foundry_agents.py")
    match = re.search(r'"authType"\s*:\s*"AgenticIdentityToken"(.{0,400})', text, re.S)
    assert match, "the A2A connection body is not written as expected"
    block = match.group(1)
    assert re.search(r'"audience"\s*:', block), (
        "the A2A connection sets no first-class properties.audience; the token cannot "
        "be minted and the hop fails before it reaches the card"
    )


def test_the_caller_is_granted_agent_consumer_on_the_project():
    """
    The single most expensive omission of this build. Without the grant the card fetch
    returns 404 — not 403 — for minutes, which reads as a wrong URL and sends you hunting
    through card paths that were correct all along. Observed: 404,404,404,403,200 in ~4min.
    """
    text = source("deploy_foundry_agents.py")
    assert "Foundry Agent Consumer" in text, \
        "the deploy never grants Foundry Agent Consumer, so the A2A hop cannot authorise"
    assert "role" in text and "assignment" in text, \
        "the role is named but never actually assigned"


def test_the_grant_uses_the_assignable_principal():
    """
    An agent exposes two principal ids and only one can appear in a role assignment.
    blueprint.principal_id is of type #microsoft.graph.agentIdentityBlueprintPrincipal
    and is rejected with PrincipalTypeNotSupported.
    """
    text = code_only("deploy_foundry_agents.py")
    assert "instance_identity" in text, \
        "the grant must read instance_identity.principal_id"
    assert not re.search(r'blueprint.{0,40}principal_id', text, re.S), \
        "blueprint.principal_id is not assignable; role assignment will be rejected"


def test_the_role_scope_is_a_bare_resource_id():
    """
    project_scope() returns a full https://management.azure.com/... URL because it feeds
    arm_request(). `az role assignment --scope` needs a BARE resource id and rejects the
    URL form with (MissingSubscription) — an error naming the account context, which is
    correct, instead of the argument that is actually malformed.
    """
    text = source("deploy_foundry_agents.py")
    match = re.search(r'def grant_agent_consumer.*?(?=\ndef )', text, re.S)
    assert match, "grant_agent_consumer is gone"
    body = match.group(0)
    assert "://" in body, (
        "the grant passes project_scope() straight to az; that value is a URL and the "
        "CLI will reject it with (MissingSubscription)"
    )


def test_the_grant_does_not_depend_on_the_cli_default_subscription():
    """
    Run standalone — outside deploy_all.py, which sets the default first — the call must
    still resolve. Otherwise the step works in the orchestrator and only in the orchestrator.
    """
    text = source("deploy_foundry_agents.py")
    match = re.search(r'def grant_agent_consumer.*?(?=\ndef )', text, re.S)
    assert "--subscription" in match.group(0), \
        "the role assignment relies on whatever subscription the CLI happens to default to"


def test_the_card_check_reads_the_nested_protocol_version():
    """
    The agent card has NO top-level `protocolVersion`; versions live per entry inside
    `supportedInterfaces`. Reading the top level printed a confident 'protocolVersion
    None' against a perfectly valid card — a check that cannot fail, later quoted as
    evidence that the card was broken.
    """
    text = source("deploy_foundry_agents.py")
    assert "supportedInterfaces" in text, (
        "the card verification does not read supportedInterfaces[].protocolVersion, so "
        "it reports None on every valid card"
    )
    assert not re.search(r'card\.get\(\s*["\']protocolVersion', text), \
        "protocolVersion is read at the top level of the card, where it never exists"


def test_the_fabric_connection_records_that_arm_cannot_validate_it():
    """
    ARM accepts a MicrosoftFabric connection and returns 200, while the Fabric data-agent
    tool resolves a CustomKeys connection of category 'AzureFabric' — a category ARM does
    not have at any api-version. 'ARM stored it' must never be presented as success.
    """
    text = source("deploy_foundry_connection.py")
    assert "AzureFabric" in text, \
        "the proven ARM limitation is not recorded where the next reader will hit it"
    assert "portal" in text.lower(), \
        "no portal fallback is offered for a step ARM provably cannot perform"


def test_both_protocols_are_relisted_together(agents_mod):
    """
    Merge-patch REPLACES arrays. Writing one protocol turns the others off — which
    silently disables `responses` and breaks the front door you just built.
    """
    text = source("deploy_foundry_agents.py")
    match = re.search(r'"protocol_configuration"\s*:\s*\{([^}]*\}[^}]*)\}', text)
    assert match, "protocol_configuration is not written"
    block = match.group(1)
    assert "responses" in block and "a2a" in block, \
        "protocol_configuration must re-list every protocol on every write"


def test_the_sdk_is_never_used_to_round_trip_the_endpoint():
    """
    AgentEndpointConfig has no `protocols` field, so agent.as_dict() returns None for a
    block the REST API returns in full. Round-tripping through the SDK silently deletes
    it. Hence: raw JSON in, raw JSON out.
    """
    assert "AgentEndpointConfig" not in code_only("deploy_foundry_agents.py")
    assert "agents_request(" in source("deploy_foundry_agents.py"), \
        "the endpoint must be written as raw REST"


# ── Client and API-version mechanics ─────────────────────────────────────────

@pytest.mark.parametrize("name", ["deploy_foundry_agents.py", "verify_foundry.py"])
def test_client_opts_into_preview(name):
    """
    Both the Fabric data agent tool and the A2A tool are preview surfaces. Without
    allow_preview=True they are simply absent, and the error never says 'preview'.
    """
    assert re.search(r"allow_preview\s*=\s*True", source(name)), \
        f"{name} builds AIProjectClient without allow_preview=True"


def test_agents_api_version_is_the_literal_v1():
    """
    A date-shaped api-version on the Agents data plane returns 400 and reads as a broken
    route. ARM connections use a dated version — the two are not interchangeable.
    """
    from foundry import foundry_common
    assert foundry_common.AGENTS_API_VERSION == "v1"
    assert re.match(r"^\d{4}-\d{2}-\d{2}", foundry_common.ARM_API_VERSION), \
        "the ARM api-version should be date-shaped; only the Agents one is 'v1'"


def test_connections_are_resolved_by_name_not_by_guid():
    """
    Code references a connection NAME so the same script promotes across environments
    unchanged. A GUID pasted into a script is how a promotion breaks.
    """
    text = source("deploy_foundry_agents.py")
    assert "connections.get(" in text
    guids = re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                       text, re.I)
    assert not guids, f"hardcoded GUIDs in the deploy script: {guids}"


# ── Region and config coherence ──────────────────────────────────────────────

def test_foundry_region_equals_the_capacity_region(config):
    """
    Every question in this demo crosses from Foundry into Fabric and back. A
    cross-region project adds a hop to a path that already has four, and splits the data
    residency story in two — the first thing a European media agency asks about.
    """
    assert config["foundry"]["region"] == config["capacity_region"].replace(" ", "").lower()


def test_the_region_check_is_enforced_not_merely_documented():
    assert "capacity_region" in source("deploy_foundry_project.py"), \
        "deploy_foundry_project must fail on a region mismatch, not just warn in a comment"


def test_config_names_every_key_the_foundry_scripts_require(config):
    required = [
        "project_name", "region", "resource_group", "account_name",
        "model_deployment_name", "model_name", "model_version",
        "orchestrator_agent_name", "contracts_agent_name",
        "fabric_connection_name", "contracts_connection_name", "knowledge_base_name",
    ]
    missing = [k for k in required if k not in config["foundry"]]
    assert not missing, f"config.example.yaml foundry block is missing: {missing}"


def test_the_two_agent_names_are_distinct(config):
    """
    Foundry agent names ARE the API identifier and there is no rename operation. A
    collision here is discovered by one agent overwriting the other.
    """
    names = {config["foundry"]["orchestrator_agent_name"],
             config["foundry"]["contracts_agent_name"],
             config["data_agent_name"]}
    assert len(names) == 3, f"agent names collide: {names}"


# ── Ordering ─────────────────────────────────────────────────────────────────

def test_foundry_steps_come_after_the_fabric_data_agent():
    """
    A connection can only point at a PUBLISHED Fabric data agent. Ordering the Foundry
    steps before data_agent produces a connection to nothing, created with HTTP 200.
    """
    import deploy_all
    names = deploy_all.STEP_NAMES
    assert names.index("data_agent") < names.index("foundry_connection")
    assert names.index("foundry_project") < names.index("foundry_connection")
    assert names.index("foundry_connection") < names.index("foundry_agents")


def test_the_two_halves_partition_the_chain():
    """
    --fabric-only exists because the Foundry half is the unproven one: a demo must be able
    to stand up the Fabric side alone. The two lists must partition STEPS exactly, or a
    step silently belongs to neither and never runs.
    """
    import deploy_all
    assert set(deploy_all.FABRIC_STEPS) | set(deploy_all.FOUNDRY_STEPS) \
        == set(deploy_all.STEP_NAMES)
    assert not set(deploy_all.FABRIC_STEPS) & set(deploy_all.FOUNDRY_STEPS)
    assert deploy_all.FABRIC_STEPS[-1] == "data_agent", \
        "--fabric-only must end on the published data agent, which is what Foundry binds to"


def test_half_filters_compose_with_a_resume():
    """
    `--fabric-only` is a FILTER on the range, not an alternative to it. It used to sit in
    the same elif chain as `--from`, so `--from preload_pacing --fabric-only` planned the
    Foundry steps anyway — the flag was parsed, listed in --help, and silently dropped.
    On a live deploy 2026-09-02 that queued an Azure Foundry resource creation nobody
    asked for.

    A flag that is quietly ignored is worse than one that errors, because the plan it
    prints looks deliberate.
    """
    import argparse
    import deploy_all

    def plan(**kw):
        args = argparse.Namespace(steps=[], from_step=None, skip=None,
                                  fabric_only=False, foundry_only=False)
        for k, v in kw.items():
            setattr(args, k, v)
        return deploy_all.select_steps(args)

    resumed = plan(from_step="preload_pacing", fabric_only=True)
    assert not set(resumed) & set(deploy_all.FOUNDRY_STEPS), \
        f"--from + --fabric-only leaked Foundry steps: {resumed}"
    assert "preload_pacing" in resumed and resumed[-1] == "data_agent"

    # the same composition on the other half, and with explicit steps
    assert plan(from_step="preload_pacing", foundry_only=True) == list(deploy_all.FOUNDRY_STEPS)
    assert plan(steps=["lakehouse", "foundry_agents"], fabric_only=True) == ["lakehouse"]

    # a range that cannot satisfy the filter must fail loudly, not run nothing
    with pytest.raises(SystemExit):
        plan(steps=["foundry_agents"], fabric_only=True)
    with pytest.raises(SystemExit):
        plan(fabric_only=True, foundry_only=True)


def test_steps_that_parse_argv_are_isolated_from_the_orchestrator():
    """
    Five step modules build their own argparse inside main(). Imported by deploy_all, they
    read the ORCHESTRATOR's sys.argv, so any flag at all killed the back half of the chain:

        deploy_all.py --from semantic_model --fabric-only
        -> deploy_all.py: error: unrecognized arguments: --from semantic_model --fabric-only

    raised from inside deploy_data_agent.main(), whose parser only knows --delete. Live,
    2026-09-02, at step 10 of 13 after the semantic model had already been created.

    Each script was fine on its own, which is exactly why the per-script tests missed it —
    the defect lives in the seam. This asserts the seam: run_steps must neutralise argv
    around every main(), and restore it afterwards.
    """
    import deploy_all

    seen = []
    sentinel = ["deploy_all.py", "--from", "semantic_model", "--fabric-only"]

    class FakeModule:
        def main(self):
            seen.append(list(sys.argv))

    real_import = deploy_all.importlib.import_module
    deploy_all.importlib.import_module = lambda name: FakeModule()
    saved = sys.argv
    sys.argv = list(sentinel)
    try:
        deploy_all.run_steps(["semantic_model", "data_agent"])
    finally:
        sys.argv = saved
        deploy_all.importlib.import_module = real_import

    assert len(seen) == 2
    for argv in seen:
        assert len(argv) == 1, f"step saw the orchestrator's flags: {argv}"
        assert argv[0].endswith(".py")
    assert sys.argv == saved, "run_steps must restore sys.argv"


# ── The verifier itself ──────────────────────────────────────────────────────

def test_verifier_asserts_the_negative_case():
    """
    Every A2A subordinate emits the same item type, so the type identifies nothing. The
    verifier must assert that the expected tool fired AND that the other did not —
    otherwise it passes while the supervisor asks the contract corpus for a number.
    """
    text = source("verify_foundry.py")
    assert "forbid" in text, "the verifier never checks that a tool stayed out of it"
    assert "forbid=[a2a_conn, contracts]" in text, (
        "the quantitative probe must forbid the contracts agent explicitly — that is "
        "the exact failure this architecture exists to prevent"
    )


def test_verifier_checks_the_answer_shape_not_just_the_routing():
    from foundry import verify_foundry
    problems = verify_foundry.check_answer_contract("Some answer with no marker.")
    assert problems, "an answer with no SOURCE block must fail the contract"

    good = "We over-delivered in the quarter.\n### SOURCE\nmeasure: delivery vs plan"
    assert not verify_foundry.check_answer_contract(good), \
        f"a well-formed answer was rejected: {verify_foundry.check_answer_contract(good)}"


def test_verifier_rejects_identifiers_in_the_prose():
    from foundry import verify_foundry
    leaked = ("Delivery ran ahead for [Delivered Impressions].\n"
              "### SOURCE\nmeasure: x")
    assert verify_foundry.check_answer_contract(leaked), \
        "a bracketed measure in the prose must be caught — that is clause 7"


def test_verifier_rejects_a_duplicated_source_block():
    from foundry import verify_foundry
    doubled = "Text.\n### SOURCE\na\nMore text.\n### SOURCE\nb"
    problems = verify_foundry.check_answer_contract(doubled)
    assert any("2 times" in p for p in problems), \
        "two provenance locations are read as two presentations, and both get filled"


def test_foundry_agent_names_use_the_charset_the_service_accepts():
    """
    Foundry agent names are NOT Fabric item names, and nothing says so at the call site.

    Observed live 2026-09-02: `agents.create_version(agent_name="Zava_Media_Contracts")`
    is rejected with

        (invalid_parameters) Must start and end with alphanumeric characters, can
        contain hyphens in the middle, and must not exceed 63 characters.

    The message names neither the value nor the field. It arrives at step 2 of 7, after
    step 1 has uploaded the entire contract corpus into a brand-new vector store, so the
    run dies having created a billable orphan.

    What makes this worth a test rather than a comment is the asymmetry: `data_agent_name`
    in the same config block is a FABRIC item, Fabric accepts underscores, and
    "Zava_Media_Analyst" is deployed and working under that exact name. A reviewer
    normalising the file to one convention breaks the deploy in whichever direction they
    choose. Both names are asserted here, in opposite directions, on purpose.
    """
    from foundry.foundry_common import FOUNDRY_AGENT_NAME_RE

    cfg = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    foundry = cfg["foundry"]

    for key in ("orchestrator_agent_name", "contracts_agent_name"):
        name = foundry[key]
        assert FOUNDRY_AGENT_NAME_RE.match(name), (
            f"foundry.{key} = {name!r} is rejected by the Agents data plane: "
            f"alphanumeric at both ends, hyphens in the middle only, 63 max. "
            f"An underscore here fails at step 2 of 7, after the corpus upload."
        )

    assert "_" in cfg["data_agent_name"], (
        "data_agent_name is a FABRIC item name and is deployed with underscores. "
        "If this ever legitimately changes, delete the assertion deliberately - do not "
        "let a global search-and-replace across the config decide it."
    )


def test_illegal_agent_names_are_rejected_before_anything_is_created():
    """The validator must run before the client, and reject exactly what the service does."""
    from foundry import foundry_common
    for bad in ("Zava_Media_Agent", "-leading", "trailing-", "a" * 64, ""):
        with pytest.raises(SystemExit):
            foundry_common.check_agent_name(bad, "foundry.some_setting")

    for good in ("Zava-Media-Agent", "a", "A1", "a-b-c", "a" * 63):
        assert foundry_common.check_agent_name(good, "x") == good

    # Ordering is the whole point: a validated name is worthless if the corpus was
    # already uploaded. Both names must be checked before _client() is reached.
    tree = ast.parse(source("deploy_foundry_agents.py"))
    main = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    called = [n.func.id for n in ast.walk(main)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert called.count("check_agent_name") == 2, \
        "both agent names must be validated, not just one"
    assert called.index("_client") > called.index("check_agent_name"), \
        "names must be validated before the client is built, let alone before the upload"

def test_the_a2a_connection_name_uses_dashes_not_underscores():
    """
    Connection names have their own charset rule, and it is not the agent rule.

    Live 2026-09-02, PUT of the A2A connection at project scope:

        ValidationError: Connection name must be 1-64 characters long and can only
        contain alphanumeric characters, dashes, and dots.

    CORRECTED 2026-09-03. This docstring used to say the rule was "enforced
    inconsistently", because `fabric_connection_name` carried an underscore and existed
    on the tenant through the identical PUT, scope and api-version. That was the wrong
    conclusion drawn from a real observation. The rule is not inconsistent, it is
    CATEGORY-DEPENDENT:

        MicrosoftFabric  -> underscores accepted   (the old Fabric connection)
        RemoteTool       -> underscores rejected   (A2A, and Fabric IQ over MCP)

    When the Fabric connection moved to RemoteTool/GenericProtocol so it could be created
    from ARM at all, it started being rejected too - same name, same call, new category.
    So both names are asserted now, and "only the body's category differs" turned out to
    be the whole explanation rather than an aside.
    """
    cfg = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))

    for key in ("contracts_connection_name", "fabric_connection_name"):
        name = cfg["foundry"][key]
        assert re.match(r"^[A-Za-z0-9.-]{1,64}$", name), (
            f"foundry.{key} = {name!r} is rejected by the service: "
            f"alphanumeric, dashes and dots only, 1-64 characters."
        )
        assert "_" not in name, (
            f"foundry.{key} = {name!r} carries an underscore. Both connections are "
            f"RemoteTool now, and that category rejects it at PUT time."
        )