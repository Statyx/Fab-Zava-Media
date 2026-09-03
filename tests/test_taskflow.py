"""
The Task Flow is imported by hand, once, in front of a customer.

There is no REST API for task flows, so nothing else validates this file. A schema mistake
surfaces as "Import failed" on the day it matters, with no line number and no clue - the
portal parses it or it does not.

Every rule below is a documented parser trap, not a style preference.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FLOW = ROOT / "taskflow" / "zava_media_taskflow.json"

# The exact strings the portal accepts. Anything else imports as "General" or fails.
VALID_TYPES = {
    "get data", "mirror data", "store data", "prepare data",
    "analyze and train data", "track data", "visualize", "distribute",
    "develop", "general",
}


@pytest.fixture(scope="module")
def raw() -> bytes:
    return FLOW.read_bytes()


@pytest.fixture(scope="module")
def flow(raw) -> dict:
    return json.loads(raw.decode("utf-8"))


def test_the_file_is_ascii_only(raw):
    """
    Unicode in any string - an arrow, an em-dash, an accented character - makes the import
    fail to parse. This is the single easiest way to break the file, because the offending
    character is invisible in a diff and the descriptions are prose.
    """
    try:
        raw.decode("ascii")
    except UnicodeDecodeError as e:
        bad = raw[e.start:e.end].decode("utf-8", "replace")
        context = raw[max(0, e.start - 60):e.start + 20].decode("utf-8", "replace")
        pytest.fail(f"non-ASCII character {bad!r} at byte {e.start}: ...{context}")


def test_the_file_has_no_bom(raw):
    """A BOM is not ASCII and not JSON. Windows editors add one silently."""
    assert not raw.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM at the start of the file"


def test_the_schema_uses_the_portal_field_names(flow):
    """
    `type` not `taskType`; `edges` not `connectors`. The near-miss names are what any
    reasonable person writes from memory, and they import as an empty canvas rather than
    an error.
    """
    assert set(flow) == {"tasks", "edges", "name", "description"}, \
        f"unexpected root keys: {sorted(set(flow))}"
    for task in flow["tasks"]:
        assert set(task) == {"type", "id", "name", "description"}, \
            f"task {task.get('name')!r} has keys {sorted(set(task))}"
    for edge in flow["edges"]:
        assert set(edge) == {"source", "target"}, \
            f"edge has keys {sorted(set(edge))}; expected source/target"


def test_no_position_is_declared(flow):
    """The portal auto-layouts. A `position` key is rejected, not ignored."""
    assert all("position" not in t for t in flow["tasks"])


def test_every_task_type_is_one_the_portal_knows(flow):
    unknown = {t["type"] for t in flow["tasks"]} - VALID_TYPES
    assert not unknown, f"task types the portal does not accept: {unknown}"


def test_task_ids_are_unique_guids(flow):
    import re
    guid = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    ids = [t["id"] for t in flow["tasks"]]
    assert len(ids) == len(set(ids)), "duplicate task id"
    for i in ids:
        assert guid.match(i), f"task id {i!r} is not GUID-shaped"


def test_every_edge_joins_two_declared_tasks(flow):
    """
    An edge to an id that no task declares does not error - it draws nothing. The canvas
    then quietly shows fewer arrows than the architecture has.
    """
    ids = {t["id"] for t in flow["tasks"]}
    for e in flow["edges"]:
        assert e["source"] in ids, f"edge source {e['source']} matches no task"
        assert e["target"] in ids, f"edge target {e['target']} matches no task"
        assert e["source"] != e["target"], "self-edge"


def test_no_task_is_stranded(flow):
    """A box with no arrow in or out reads as forgotten, not as independent."""
    touched = {e["source"] for e in flow["edges"]} | {e["target"] for e in flow["edges"]}
    stranded = [t["name"] for t in flow["tasks"] if t["id"] not in touched]
    assert not stranded, f"tasks with no connector: {stranded}"


def test_the_canvas_matches_the_deployed_items(flow):
    """
    The task flow is documentation, and documentation drifts. If an item is renamed in
    config.example.yaml, the canvas still says the old name and sends the operator looking
    for something that does not exist.
    """
    import yaml
    cfg = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    blob = json.dumps(flow)
    for key in ("lakehouse_name", "eventhouse_name", "ontology_name",
                "semantic_model_name", "report_name", "data_agent_name"):
        assert cfg[key] in blob, \
            f"{key} is '{cfg[key]}' in config but that name is absent from the task flow"


def test_the_foundry_agents_are_not_on_the_canvas(flow):
    """
    A task flow maps Fabric items. The Foundry supervisor and contracts agent live in a
    different resource provider and cannot be assigned to a task - putting them here
    implies Fabric owns them, which is exactly the boundary this demo exists to draw.
    """
    import yaml
    cfg = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    blob = json.dumps(flow)
    for key in ("orchestrator_agent_name", "contracts_agent_name"):
        assert cfg["foundry"][key] not in blob, \
            f"{cfg['foundry'][key]} is a Foundry agent and cannot be a Fabric task"
