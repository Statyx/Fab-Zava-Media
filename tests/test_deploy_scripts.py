"""Deploy-chain guards for Zava Media — offline, no Fabric tenant needed.

test_smoke.py guards the DATASET. This file guards the SCRIPTS that push it into
Fabric, and above all the seams between them. Every failure here is one that would
otherwise surface as a silent, wrong-looking-right deploy:

  * an ontology entity bound to a column that no longer exists in the CSV
  * a semantic-model measure the data agent tells the LLM to use, that isn't in the model
  * a relationship pointing at a table that was renamed
  * a data agent written to draft/ only, therefore invisible to Foundry
  * a second join path to dim_advertiser, which Power BI would silently deactivate

Run:  python -m pytest tests/ -v --tb=short -p no:cacheprovider
"""
import ast
import csv
import importlib
import pathlib
import re
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
RAW = ROOT / "data" / "raw"
sys.path.insert(0, str(SRC))

# Modules that talk to Fabric must repair PATH and force UTF-8 stdout before anything
# else. generate_data.py is exempt: it is pure offline generation and imports no helper.
FABRIC_MODULES = sorted(
    p.name for p in SRC.glob("*.py")
    if re.match(r"^(deploy_|preload_|refresh_)", p.name)
)


def _csv_header(name):
    with (RAW / f"{name}.csv").open(encoding="utf-8", newline="") as fh:
        return next(csv.reader(fh))


@pytest.fixture(scope="module")
def bim():
    """The semantic model as it would actually be pushed, minus the network call."""
    import deploy_semantic_model as dsm
    dsm.API_BASE = "https://api.fabric.microsoft.com/v1"
    model = dsm.build_model_bim(
        {"lakehouse_name": "ZavaMediaLH", "fabric_api_base": dsm.API_BASE},
        {"workspace_id": "w", "lakehouse_id": "l",
         "lakehouse_sql_endpoint": "<sql_endpoint>.datawarehouse.fabric.microsoft.com"},
    )["model"]
    return model


@pytest.fixture(scope="module")
def sm_index(bim):
    """table -> {"columns": {...}, "measures": {...}} for cross-file assertions."""
    return {t["name"]: {"columns": {c["name"] for c in t.get("columns", [])},
                        "measures": {m["name"] for m in t.get("measures", [])}}
            for t in bim["tables"]}


# ── Script hygiene ──────────────────────────────────────────────
@pytest.mark.parametrize("name", FABRIC_MODULES)
def test_fabric_scripts_bootstrap_first(name):
    """bootstrap() must run before any third-party import.

    It repairs PATH (so `az` is findable) and forces stdout to UTF-8. Import a
    module that prints a check mark before bootstrap and the script dies on a
    Windows console with a UnicodeEncodeError, several minutes into a deploy.
    """
    tree = ast.parse((SRC / name).read_text(encoding="utf-8"))
    stdlib_ok = set(sys.stdlib_module_names) | {"platform_env"}
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) \
                and getattr(node.value.func, "id", None) == "bootstrap":
            return  # reached bootstrap() with no foreign import before it
        if isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] in stdlib_ok for a in node.names), \
                f"{name}: import before bootstrap()"
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] in stdlib_ok, \
                f"{name}: 'from {node.module} import ...' before bootstrap()"
    pytest.fail(f"{name} never calls bootstrap()")


@pytest.mark.parametrize("py", sorted(SRC.glob("*.py")), ids=lambda p: p.name)
def test_no_hardcoded_guids(py):
    """Tenant, capacity and item GUIDs belong in the gitignored config/state, never in code."""
    text = py.read_text(encoding="utf-8")
    found = re.findall(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                       r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", text)
    # a0000000-...-00000000000a style placeholders are deliberately fake and allowed
    real = [g for g in found if not re.fullmatch(r"[a0-]+", g.lower())]
    assert not real, f"{py.name} carries hardcoded GUID(s): {real}"


@pytest.mark.parametrize("py", sorted(SRC.glob("*.py")), ids=lambda p: p.name)
def test_no_bare_shell_true(py):
    """subprocess(..., shell=True) is a portability and injection trap.

    The one legitimate case is `az` on Windows, which is a .cmd shim CreateProcess
    cannot launch directly; that is what platform_env.AZ_NEEDS_SHELL exists for.
    Checked on the AST, so the constant's own docstring and comments don't trip it.
    """
    for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) \
                    and kw.value.value is True:
                pytest.fail(f"{py.name}:{node.lineno} use shell=AZ_NEEDS_SHELL, "
                            f"not a literal shell=True")


# ── deploy_all: the orchestrator must actually be able to run ────
def test_deploy_all_steps_all_exist_and_expose_main():
    import deploy_all
    for step, module_name in deploy_all.STEPS:
        mod = importlib.import_module(module_name)
        assert hasattr(mod, "main"), f"step '{step}' -> {module_name} has no main()"


def test_deploy_all_order_respects_dependencies():
    import deploy_all
    order = [s for s, _ in deploy_all.STEPS]
    # (earlier, later) — each pair is a hard dependency, not a preference.
    for earlier, later in [
        ("generate_data", "lakehouse"),      # nothing to upload otherwise
        ("workspace", "lakehouse"),
        ("lakehouse", "setup_notebook"),     # notebook converts the uploaded CSVs
        ("setup_notebook", "ontology"),      # ontology binds to Delta tables
        ("eventhouse", "preload_pacing"),
        ("preload_pacing", "ontology"),      # TimeSeries binding needs the KQL table
        ("ontology", "graph"),               # graph is the ontology's child item
        ("setup_notebook", "semantic_model"),
        ("ontology", "data_agent"),          # both sources must exist first
        ("semantic_model", "data_agent"),
    ]:
        assert order.index(earlier) < order.index(later), \
            f"'{earlier}' must run before '{later}'"


# ── Lakehouse <-> generated CSVs ─────────────────────────────────
def test_batch_tables_match_the_generated_csvs():
    """BATCH_TABLES is the single source of truth for what lands as Delta.

    pacing_events is deliberately absent: it goes to the Eventhouse, not the Lakehouse.
    """
    from deploy_lakehouse import BATCH_TABLES
    on_disk = {p.stem for p in RAW.glob("*.csv")}
    assert set(BATCH_TABLES) == on_disk - {"pacing_events"}, (
        f"BATCH_TABLES drifted from data/raw/: "
        f"missing={on_disk - {'pacing_events'} - set(BATCH_TABLES)}, "
        f"extra={set(BATCH_TABLES) - on_disk}"
    )


def test_setup_notebook_uses_the_same_table_list():
    """The notebook must import BATCH_TABLES, not restate it.

    A duplicated list is how a table gets uploaded and never converted to Delta.
    """
    text = (SRC / "deploy_setup_notebook.py").read_text(encoding="utf-8")
    assert "from deploy_lakehouse import BATCH_TABLES" in text


def test_calendar_columns_stay_strings_in_the_notebook():
    """inferSchema turns date_key into a date but leaves month ('2026-04') a string.

    Mixed types silently break the monthly-plan to daily-delivery join that the whole
    over-delivery figure rests on — no error, just wrong numbers.
    """
    from deploy_setup_notebook import STRING_COLUMNS
    for col in ("date_key", "month", "quarter"):
        assert col in STRING_COLUMNS, f"'{col}' must be forced to STRING"


# ── Ontology <-> CSVs ────────────────────────────────────────────
def test_ontology_entities_bind_to_existing_tables_and_columns():
    """An entity bound to a missing column yields an EMPTY GRAPH, not an error."""
    from deploy_ontology import ENTITIES, DISPLAY_PROPERTY
    from deploy_lakehouse import BATCH_TABLES
    for name, table, keys, cols in ENTITIES:
        assert table in BATCH_TABLES, f"entity {name} binds to unknown table '{table}'"
        header = _csv_header(table)
        for key in keys:
            assert key in header, f"entity {name}: key '{key}' absent from {table}.csv"
        for col, _dtype in cols:
            assert col in header, f"entity {name}: property '{col}' absent from {table}.csv"
        if name in DISPLAY_PROPERTY:
            assert DISPLAY_PROPERTY[name] in {c for c, _ in cols}, \
                f"entity {name}: display property is not one of its own properties"


def test_ontology_relationship_foreign_keys_exist():
    """Both binding sides are columns of fk_table: the one identifying the source, and
    the one holding the target's key. Getting that backwards yields an empty graph,
    silently — the deploy reports success and the agent finds nothing."""
    from deploy_ontology import ENTITIES, RELATIONSHIPS
    entity_names = {e[0] for e in ENTITIES}
    for label, source, target, fk_table, src_cols, tgt_cols in RELATIONSHIPS:
        assert source in entity_names, f"relationship {label}: unknown source '{source}'"
        assert target in entity_names, f"relationship {label}: unknown target '{target}'"
        header = _csv_header(fk_table)
        for col in list(src_cols) + list(tgt_cols):
            assert col in header, f"relationship {label}: '{col}' absent from {fk_table}.csv"


def test_ontology_timeseries_binds_to_the_streamed_table():
    """The TimeSeries binding is what makes the ontology span batch AND live data."""
    from deploy_ontology import ENTITIES, TIMESERIES
    entity_names = {e[0] for e in ENTITIES}
    for entity, (kql_table, ts_col, key_col, metrics) in TIMESERIES.items():
        assert entity in entity_names, f"TimeSeries bound to unknown entity '{entity}'"
        header = _csv_header(kql_table)
        for col in [ts_col, key_col] + [m for m, _ in metrics]:
            assert col in header, f"TimeSeries {entity}: '{col}' absent from {kql_table}.csv"


def test_graph_reuses_the_ontology_definition():
    """deploy_graph must import ENTITIES/RELATIONSHIPS — a second copy would drift."""
    text = (SRC / "deploy_graph.py").read_text(encoding="utf-8")
    assert "from deploy_ontology import" in text
    assert "ENTITIES" in text and "RELATIONSHIPS" in text


# ── Semantic model ───────────────────────────────────────────────
def test_semantic_model_covers_every_batch_table(sm_index):
    from deploy_lakehouse import BATCH_TABLES
    assert set(sm_index) == set(BATCH_TABLES), (
        f"semantic model tables differ from the Delta tables: "
        f"missing={set(BATCH_TABLES) - set(sm_index)}, extra={set(sm_index) - set(BATCH_TABLES)}"
    )


def test_semantic_model_columns_exist_in_the_csvs(sm_index):
    for table, parts in sm_index.items():
        header = set(_csv_header(table))
        unknown = parts["columns"] - header
        assert not unknown, f"{table}: model columns absent from the CSV: {sorted(unknown)}"


def test_no_measure_collides_with_a_column_name(sm_index):
    """
    Tabular refuses a measure whose name matches a column in the same table, and the
    comparison is CASE-INSENSITIVE: a `clicks` column and a `Clicks` measure collide.

    This one is expensive to find at deploy time. The import is rejected wholesale -
    "The 'Clicks' measure cannot be created because a column with the same name already
    exists" - and it surfaces at step 9 of 13, minutes in, after the workspace, lakehouse,
    notebook, eventhouse, ontology and graph have all succeeded. Observed on a live
    deploy 2026-09-02.

    Ten seconds offline instead.
    """
    for table, parts in sm_index.items():
        cols = {c.casefold(): c for c in parts["columns"]}
        for measure in parts["measures"]:
            clash = cols.get(measure.casefold())
            assert clash is None, (
                f"{table}: measure [{measure}] collides with column [{clash}] "
                f"(Tabular compares names case-insensitively). "
                f"Rename the measure - the column name is referenced by the DAX."
            )


def test_measure_references_resolve_to_declared_measures(bim, sm_index):
    """
    A DAX expression citing [Some Measure] that no table declares does not fail at import
    - it fails when a visual or the agent evaluates it. Renaming a measure and missing one
    of its call sites is exactly how that happens, so the rename is checked mechanically.
    """
    declared = {m for parts in sm_index.values() for m in parts["measures"]}
    columns = {c for parts in sm_index.values() for c in parts["columns"]}
    for table in bim["tables"]:
        for measure in table.get("measures", []):
            expr = measure["expression"]
            if isinstance(expr, list):
                expr = "\n".join(expr)
            # [Name] not preceded by a table reference is a measure reference;
            # table[column] is a column reference and is checked elsewhere.
            for ref in re.findall(r"(?<![\w'\]])\[([^\]]+)\]", expr):
                assert ref in declared or ref in columns, (
                    f"{table['name']}[{measure['name']}] references [{ref}], "
                    f"which is neither a declared measure nor a column"
                )


def test_semantic_model_relationships_resolve(bim, sm_index):
    for rel in bim["relationships"]:
        assert rel["fromColumn"] in sm_index[rel["fromTable"]]["columns"], \
            f"{rel['name']}: {rel['fromTable']}[{rel['fromColumn']}] does not exist"
        assert rel["toColumn"] in sm_index[rel["toTable"]]["columns"], \
            f"{rel['name']}: {rel['toTable']}[{rel['toColumn']}] does not exist"


def test_no_ambiguous_second_path_to_the_advertiser(bim):
    """The advertiser is reached via Advertiser -> Brand -> Campaign, and only that way.

    Adding dim_campaign[advertiser_id] -> dim_advertiser creates a second path;
    Power BI then deactivates one relationship without telling anyone, and the
    advertiser-level over-delivery figure changes.
    """
    inbound = [r for r in bim["relationships"] if r["toTable"] == "dim_advertiser"]
    assert len(inbound) == 1, \
        f"{len(inbound)} relationships point at dim_advertiser: {[r['name'] for r in inbound]}"
    assert inbound[0]["fromTable"] == "dim_brand"


def test_load_bearing_measure_is_hand_checkable(bim):
    """[Delivery vs Plan %] is the demo's answer. It must stay a ratio of two
    measures the client can read off the screen and verify."""
    measures = {m["name"]: m for t in bim["tables"] for m in t.get("measures", [])}
    for name in ("Delivery vs Plan %", "Planned Impressions", "Delivered Impressions"):
        assert name in measures, f"missing measure [{name}]"
    expr = measures["Delivery vs Plan %"]["expression"]
    expr = expr if isinstance(expr, str) else "\n".join(expr)
    assert "[Delivered Impressions]" in expr and "[Planned Impressions]" in expr


def test_model_holds_no_contractual_terms(bim):
    """The Fabric/Foundry boundary is encoded in the model, not just in a prompt.

    A column named like a contractual entitlement would let the agent answer the
    half of the question it must refuse.
    """
    banned = re.compile(r"make.?good|penalt|entitle|compensation|clause", re.I)
    for t in bim["tables"]:
        for c in t.get("columns", []):
            assert not banned.search(c["name"]), \
                f"{t['name']}[{c['name']}] looks contractual — that belongs to Foundry"
        for m in t.get("measures", []):
            assert not banned.search(m["name"]), \
                f"[{m['name']}] looks contractual — that belongs to Foundry"


# ── Data agent <-> semantic model & ontology ─────────────────────
def test_data_agent_only_cites_measures_that_exist(sm_index):
    """The agent's instructions name measures for the LLM to call.

    Name one that was renamed and the model invents DAX instead — plausible,
    unverifiable, wrong.
    """
    import deploy_data_agent as dda
    from deploy_ontology import RELATIONSHIPS
    all_measures = {m for parts in sm_index.values() for m in parts["measures"]}
    text = dda.AI_INSTRUCTIONS + "\n" + "\n".join(q + " " + d for q, d in dda.SM_FEWSHOT_PAIRS)
    cited = set(re.findall(r"\[([A-Z][^\[\]]{2,40})\]", text))
    # [:EdgeLabel] in the GQL guidance, and "Alias", [Measure] column names in DAX,
    # are not measure references.
    cited -= {r[0] for r in RELATIONSHIPS}
    cited -= set(re.findall(r'"([^"]+)"\s*,\s*\[', text))
    unknown = {c for c in cited if c not in all_measures}
    assert not unknown, f"data agent cites measures that do not exist: {sorted(unknown)}"


def test_data_agent_elements_match_the_model(sm_index):
    import deploy_data_agent as dda
    for table in dda.build_sm_elements():
        tname = table["display_name"]
        assert tname in sm_index, f"exposed table '{tname}' is not in the semantic model"
        for child in table["children"]:
            if child["type"].endswith(".column"):
                assert child["display_name"] in sm_index[tname]["columns"], \
                    f"{tname}[{child['display_name']}] exposed but absent from the model"
            elif child["type"].endswith(".measure"):
                allm = {m for p in sm_index.values() for m in p["measures"]}
                assert child["display_name"] in allm, \
                    f"[{child['display_name']}] exposed but absent from the model"


def test_data_agent_gql_uses_declared_labels_only():
    """Few-shots are copied verbatim by the LLM. A wrong edge label returns nothing."""
    import deploy_data_agent as dda
    from deploy_ontology import ENTITIES, RELATIONSHIPS
    entities = {e[0] for e in ENTITIES}
    rels = {r[0] for r in RELATIONSHIPS}
    for question, gql in dda.FEWSHOTS:
        for label in re.findall(r"-\[:(\w+)\]", gql):
            assert label in rels, f"few-shot '{question}': unknown relationship '{label}'"
        for label in re.findall(r"\(\w*:(\w+)", gql):
            assert label in entities, f"few-shot '{question}': unknown entity '{label}'"


def test_data_agent_is_published_not_just_drafted():
    """A draft-only agent does not appear in the portal and cannot be attached as a
    Foundry tool. It looks deployed and is unusable."""
    import deploy_data_agent as dda
    parts = dda.build_parts("ws", "Zava_Media_Analyst", "ont", "ONT_Zava_Media",
                            "sm", "SM_Zava_Media")
    paths = [p["path"] for p in parts]
    assert len(paths) == 12, f"expected 12 definition parts, got {len(paths)}"
    draft = {p.split("/draft/", 1)[1] for p in paths if "/draft/" in p}
    published = {p.split("/published/", 1)[1] for p in paths if "/published/" in p}
    assert draft and draft == published, \
        f"draft/ and published/ trees differ: {draft ^ published}"
    assert "Files/Config/publish_info.json" in paths


def test_data_agent_refuses_contract_questions():
    """The refusal IS the demo: it is what hands the question to Foundry."""
    import deploy_data_agent as dda
    instructions = dda.AI_INSTRUCTIONS.lower()
    assert "no contractual terms" in instructions
    assert "do not speculate" in instructions
    assert "rebate_pct" in dda.AI_INSTRUCTIONS, \
        "the agent must be told the rebate is owner-to-agency, not a client entitlement"


# ── Eventhouse ───────────────────────────────────────────────────
def test_kql_columns_match_the_csv_in_order():
    """Kusto CSV ingestion is positional. A reordered column silently loads
    campaign IDs into the channel column."""
    cfg = yaml.safe_load((SRC / "config.example.yaml").read_text(encoding="utf-8"))
    declared = [c["name"] for c in cfg["kql_tables"]["pacing_events"]["columns"]]
    assert declared == _csv_header("pacing_events")
