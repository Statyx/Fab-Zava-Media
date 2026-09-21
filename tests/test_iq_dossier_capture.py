"""Recorder contracts; synthetic responses here are never shipped as recorded evidence."""
import base64
from copy import deepcopy
import json
import re
import subprocess
from types import SimpleNamespace
import uuid

import pytest

from foundry import capture_iq_dossiers as capture


@pytest.fixture
def reference():
    return json.loads(capture.REFERENCE.read_text(encoding="utf-8"))


@pytest.fixture
def item(reference):
    return reference["cases"][0]


def jwt(tenant, expiry=4102444800):
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return f"{encode({'alg': 'test'})}.{encode({'tid': tenant, 'exp': expiry})}.test"


def dax_payload(item):
    planned = item["facts"]["planned"]
    delivered = item["facts"]["delivered"]
    first_plan, first_delivery = planned // 2, delivered // 2
    rows = []
    for cid, p, d in zip(item["campaignIds"], [first_plan, planned - first_plan],
                         [first_delivery, delivered - first_delivery]):
        rows.append({
            "[rowType]": "campaign", "[campaignId]": cid,
            "[planned]": p, "[delivered]": d, "[variance]": d / p - 1,
        })
    rows.append({
        "[rowType]": "total", "[campaignId]": "",
        **{f"[{key}]": value for key, value in item["facts"].items()},
    })
    return {"results": [{"tables": [{"rows": rows}]}]}


def graph_payload(ids):
    return {
        "status": {"code": "00000"},
        "result": {"kind": "TABLE", "columns": [{"alias": "campaignId"}],
                   "data": [{"campaignId": value} for value in ids]},
    }


def synthetic_answer(item):
    if item["id"] == "contoso-es":
        return (
            "Synthetic test fixture: Contoso Mobility Spain 2026-Q3. "
            "Master agreement ZM-ADV-001-2026 article 6.2 requires a credit when over-delivery "
            "exceeds 10%, within 45 days of quarter close. Article 6.4 assesses by market and quarter. "
            "The credit amount needs contracted channel rates."
        )
    return (
        "Synthetic test fixture: Litware Retail United Kingdom 2026-Q3. "
        "Master agreement ZM-ADV-004-2026 articles 6.1 and 6.2: no credit or compensation "
        "is due for this variance. Article 6.3 prohibits billing the excess. "
        "This does not establish that other account issues are resolved."
    )


def record(item, reference):
    dax, gql = capture.queries(item)
    return {
        "id": item["id"], "prompt": capture.dossier_prompt(item, reference["asOf"]),
        "capturedAt": "2026-09-15T12:00:00+00:00", "seconds": 1,
        "text": synthetic_answer(item),
        "toolsFired": ["DataAgent_Zava_Media_Analyst", "zava-media-contracts-a2a"],
        "citations": [], "facts": dict(item["facts"]), "campaignIds": item["campaignIds"],
        "dax": dax, "gql": gql,
    }


def test_prompt_exactly_matches_typescript_template(reference):
    source = (capture.ROOT / "app" / "src" / "domain" / "dossier.ts").read_text(encoding="utf-8")
    body = source.split("export function dossierPrompt(", 1)[1].split("\n}", 1)[0]
    templates = re.findall(r"`([^`]*)`", body)
    assert templates
    for case in reference["cases"]:
        def expression(match):
            expr = match.group(1)
            if expr == "asOf":
                return reference["asOf"]
            if expr == "item.campaignIds.join(', ')":
                return ", ".join(case["campaignIds"])
            assert expr.startswith("item.") and expr[5:] in case, f"New TS expression: {expr}"
            return case[expr[5:]]
        expected = re.sub(r"\$\{([^}]+)\}", expression, "".join(templates))
        assert capture.dossier_prompt(case, reference["asOf"]) == expected
        assert not re.search(r"45|50\s*%|10\s*%|6\.2|no credit|exclud", expected, re.I)


def test_cached_token_explicit_tenant_and_no_auth_mutations(monkeypatch, capsys):
    tenant = str(uuid.uuid4())
    token = jwt(tenant)
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["shell"] == capture.platform_env.AZ_NEEDS_SHELL
        assert kwargs["stdin"] == subprocess.DEVNULL
        return SimpleNamespace(returncode=0, stdout=json.dumps({"accessToken": token}), stderr="")
    monkeypatch.setattr(capture.subprocess, "run", run)
    for audience in capture.AUDIENCES.values():
        assert capture.cached_token(tenant, audience) == token
    assert all(c[:3] == ["az", "account", "get-access-token"] for c in commands)
    assert all(c[c.index("--tenant") + 1] == tenant for c in commands)
    assert all("--subscription" not in c for c in commands)
    assert [c[c.index("--resource") + 1] for c in commands] == list(capture.AUDIENCES.values())
    assert token not in capsys.readouterr().out


def test_wrong_tenant_and_expired_tokens_are_rejected():
    tenant = str(uuid.uuid4())
    with pytest.raises(capture.CaptureError, match="different tenant"):
        capture.validate_token(jwt(str(uuid.uuid4())), tenant)
    with pytest.raises(capture.CaptureError, match="expired"):
        capture.validate_token(jwt(tenant, expiry=100), tenant, now=200)
    with pytest.raises(capture.CaptureError, match="invalid"):
        capture.validate_token("not-a-token", tenant)


@pytest.mark.parametrize("claims", [{}, {"tid": "not-uuid", "exp": 9999999999}, {"tid": None}])
def test_malformed_token_claims_rejected(claims):
    tenant = str(uuid.uuid4())
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    with pytest.raises(capture.CaptureError):
        capture.validate_token(f"header.{encoded}.test", tenant)


def test_auth_failure_is_actionable_and_sanitized(monkeypatch):
    tenant = str(uuid.uuid4())
    token = jwt(tenant)
    monkeypatch.setattr(capture.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout="", stderr=f"AADSTS50076: cached credential needs verification. {token}",
    ))
    with pytest.raises(capture.CaptureError, match="AADSTS50076") as error:
        capture.cached_token(tenant, capture.AUDIENCES["fabric"])
    assert token not in str(error.value)


def test_queries_use_measures_and_relationship_filters_not_expected_ids(item):
    dax, gql = capture.queries(item)
    for name in ("Planned Impressions", "Delivered Impressions", "Delivery vs Plan %"):
        assert f"[{name}]" in dax
    for value in (item["advertiserId"], item["marketId"], item["quarter"]):
        assert value in dax and value in gql
    assert all(cid not in dax and cid not in gql for cid in item["campaignIds"])
    assert "SUMMARIZECOLUMNS" in dax
    assert "CampaignForAdvertiser" in gql and "CampaignInMarket" in gql
    assert "RETURN DISTINCT c.campaign_id AS campaignId" in gql


def test_dax_scoped_totals_and_campaign_ids(item):
    facts, ids = capture.dax_evidence(dax_payload(item), item)
    assert facts == item["facts"]
    assert ids == sorted(item["campaignIds"])


@pytest.mark.parametrize("payload", [
    {"error": {"message": "Denied"}},
    {"results": [{"error": {"code": "DAX failed"}, "tables": []}]},
    {"results": [{"tables": [{"rows": [], "error": {"code": "Truncated"}}]}]},
])
def test_http_200_embedded_data_errors_rejected(item, payload):
    with pytest.raises(capture.CaptureError, match="data error"):
        capture.dax_evidence(payload, item)


@pytest.mark.parametrize("mutation", ["same-count-wrong-ids", "duplicate", "total", "campaign-total", "empty", "nan"])
def test_incomplete_or_inconsistent_dax_rejected(item, mutation):
    payload = dax_payload(item)
    rows = payload["results"][0]["tables"][0]["rows"]
    if mutation == "same-count-wrong-ids":
        rows[0]["[campaignId]"] = "CMP-9999"
    elif mutation == "duplicate":
        rows[1]["[campaignId]"] = rows[0]["[campaignId]"]
    elif mutation == "total":
        rows.pop()
    elif mutation == "campaign-total":
        rows[0]["[planned]"] += 1
    elif mutation == "empty":
        rows.clear()
    else:
        rows[-1]["[variance]"] = float("nan")
    with pytest.raises(capture.CaptureError):
        capture.dax_evidence(payload, item)


def test_graph_structured_status_and_exact_membership(item):
    expected = item["campaignIds"]
    assert capture.graph_evidence(graph_payload(expected + expected), expected) == sorted(expected)
    for payload in [
        {"status": {"code": "42000"}, "result": graph_payload(expected)["result"]},
        {"status": {"code": "00000"}, "result": {"kind": "TEXT", "data": expected}},
        graph_payload(["CMP-9998", "CMP-9999"]),
        graph_payload([]),
        {"status": {"code": "00000"}, "result": {"kind": "TABLE", "data": [{"wrongAlias": expected[0]}]}},
    ]:
        with pytest.raises(capture.CaptureError):
            capture.graph_evidence(payload, expected)


def test_substantive_actual_sources_required(reference):
    for item in reference["cases"]:
        answer = synthetic_answer(item)
        tools = ["DataAgent_Zava_Media_Analyst", "zava-media-contracts-a2a"]
        capture.verify_answer(item, answer, tools, [])
        for text, fired in [
            ("", tools), (answer, []), (answer, ["mcp_list_tools"]),
            (answer, ["zava-media-contracts-a2a"]),
            (answer + " I could not retrieve the contract.", tools),
            (answer.replace(item["advertiser"], "Different advertiser"), tools),
            (answer.replace(item["contract"]["reference"], "unknown"), tools),
            (answer.replace("6.2", "9.9").replace("6.1", "9.8"), tools),
        ]:
            with pytest.raises(capture.CaptureError):
                capture.verify_answer(item, text, fired, [])


@pytest.mark.parametrize("case_index,contradiction", [
    (0, "No credit is due."),
    (0, "No compensation is required."),
    (0, "The compensation is excluded."),
    (1, "The agency must issue a credit."),
    (1, "The contract requires a compensation credit."),
])
def test_contradiction_rejected_even_when_clause_terms_and_tools_are_present(
    reference, case_index, contradiction,
):
    item = reference["cases"][case_index]
    with pytest.raises(capture.CaptureError, match="contradicts"):
        capture.verify_answer(
            item, synthetic_answer(item) + " " + contradiction,
            ["DataAgent_Zava_Media_Analyst", "zava-media-contracts-a2a"], [],
        )


@pytest.mark.parametrize("field", ["text", "toolsFired", "facts", "campaignIds", "dax", "gql", "prompt", "capturedAt"])
def test_incomplete_record_rejected(item, reference, field):
    valid = record(item, reference)
    capture.validate_record(valid, item, reference["asOf"])
    broken = deepcopy(valid)
    broken.pop(field)
    with pytest.raises(capture.CaptureError):
        capture.validate_record(broken, item, reference["asOf"])


def test_capture_calls_independent_sources_and_preserves_response(monkeypatch, item, reference):
    called = []
    def post(url, token, body, source):
        called.append((url, body, source))
        return dax_payload(item) if source == "DAX" else graph_payload(item["campaignIds"])
    def ask(endpoint, agent, prompt, token):
        assert prompt == capture.dossier_prompt(item, reference["asOf"])
        return synthetic_answer(item), ["DataAgent", "contracts"], [], "", 0.1
    monkeypatch.setattr(capture, "post_query", post)
    monkeypatch.setattr(capture, "ask_supervisor", ask)
    state = {key: str(uuid.uuid4()) for key in ("workspace_id", "semantic_model_id", "graph_model_id")}
    state.update(foundry_endpoint="https://example.test", foundry_supervisor_agent="existing-agent")
    result = capture.capture_case(item, reference, state, dict.fromkeys(capture.AUDIENCES, "test"))
    assert [call[2] for call in called] == ["DAX", "Graph"]
    assert result["text"] == synthetic_answer(item)
    assert result["citations"] == []
    assert result["campaignIds"] == item["campaignIds"]
    capture.validate_record(result, item, reference["asOf"])


def test_bad_graph_never_calls_supervisor(monkeypatch, item, reference):
    monkeypatch.setattr(capture, "post_query", lambda url, token, body, source:
                        dax_payload(item) if source == "DAX" else graph_payload(["CMP-9999"]))
    monkeypatch.setattr(capture, "ask_supervisor", lambda *args: pytest.fail("Graph was not verified"))
    state = dict.fromkeys(("workspace_id", "semantic_model_id", "graph_model_id"), "fixture")
    with pytest.raises(capture.CaptureError, match="disagree"):
        capture.capture_case(item, reference, state, dict.fromkeys(capture.AUDIENCES, "test"))


def test_atomic_writer_keeps_old_file_when_replace_fails(monkeypatch):
    # Use the repository, never the machine's temporary directories.
    path = capture.ROOT / "tests" / f".iq-capture-{uuid.uuid4().hex}.json"
    original_replace = capture.os.replace
    try:
        capture.atomic_write(path, {"cases": []})
        previous = path.read_bytes()
        def fail(*args):
            raise OSError("replace failed")
        monkeypatch.setattr(capture.os, "replace", fail)
        with pytest.raises(OSError, match="replace failed"):
            capture.atomic_write(path, {"cases": [{"id": "test"}]})
        assert path.read_bytes() == previous
        assert not list(path.parent.glob(f".{path.name}.*.pending"))
        monkeypatch.setattr(capture.os, "replace", original_replace)
        capture.atomic_write(path, {"cases": [{"id": "test"}]})
        assert json.loads(path.read_text(encoding="utf-8"))["cases"][0]["id"] == "test"
    finally:
        if path.exists():
            path.unlink()


def test_blocked_auth_leaves_empty_capture_and_nonzero_exit(monkeypatch, reference, capsys):
    writes = []
    class MissingOutput:
        @staticmethod
        def exists():
            return False
    class Config:
        @staticmethod
        def read_text(**kwargs):
            return json.dumps({"tenant_id": str(uuid.uuid4())})
    class State:
        @staticmethod
        def read_text(**kwargs):
            return json.dumps(dict.fromkeys(
                ("workspace_id", "semantic_model_id", "graph_model_id",
                 "foundry_endpoint", "foundry_supervisor_agent"), "configured"))
    def no_auth(*args):
        raise capture.CaptureError("Cached credential unavailable.")
    monkeypatch.setattr(capture, "OUTPUT", MissingOutput())
    monkeypatch.setattr(capture, "CONFIG_FILE", Config())
    monkeypatch.setattr(capture, "STATE_FILE", State())
    monkeypatch.setattr(capture, "atomic_write", lambda path, payload: writes.append(deepcopy(payload)))
    monkeypatch.setattr(capture, "cached_token", no_auth)
    monkeypatch.setattr(capture, "capture_case", lambda *args: pytest.fail("No authenticated request allowed"))
    assert capture.main([]) == 1
    assert writes[-1] == {
        "fingerprint": reference["fingerprint"], "scenarioId": reference["scenarioId"],
        "asOf": reference["asOf"], "cases": [],
    }
    assert "Cached credential unavailable" in capsys.readouterr().err


def test_generated_capture_is_compatible_and_contains_only_complete_cases(reference):
    assert capture.OUTPUT.exists(), "Run the recorder, even when authentication is blocked."
    payload = json.loads(capture.OUTPUT.read_text(encoding="utf-8"))
    assert all(payload[key] == reference[key] for key in ("fingerprint", "scenarioId", "asOf"))
    assert len({r["id"] for r in payload["cases"]}) == len(payload["cases"])
    for saved in payload["cases"]:
        case = next(c for c in reference["cases"] if c["id"] == saved["id"])
        capture.validate_record(saved, case, reference["asOf"])


def test_partial_run_saves_only_completed_cases_and_exits_nonzero(monkeypatch, reference, capsys):
    writes = []
    class FakeFile:
        def __init__(self, content=None):
            self.content = content
        def exists(self):
            return self.content is not None
        def read_text(self, **kwargs):
            return json.dumps(self.content)
    monkeypatch.setattr(capture, "OUTPUT", FakeFile())
    monkeypatch.setattr(capture, "CONFIG_FILE", FakeFile({"tenant_id": str(uuid.uuid4())}))
    monkeypatch.setattr(capture, "STATE_FILE", FakeFile(dict.fromkeys(
        ("workspace_id", "semantic_model_id", "graph_model_id",
         "foundry_endpoint", "foundry_supervisor_agent"), "configured")))
    monkeypatch.setattr(capture, "cached_token", lambda *args: "test")
    monkeypatch.setattr(capture, "atomic_write", lambda path, payload: writes.append(deepcopy(payload)))
    def case(item, reference, state, tokens):
        if item["id"] == reference["cases"][1]["id"]:
            raise capture.CaptureError("Graph source failed.")
        return record(item, reference)
    monkeypatch.setattr(capture, "capture_case", case)
    assert capture.main([]) == 1
    assert len(writes) == 2
    assert writes[0]["cases"] == []
    assert [r["id"] for r in writes[-1]["cases"]] == [reference["cases"][0]["id"]]
    assert "INCOMPLETE litware-uk: Graph source failed" in capsys.readouterr().err


def test_complete_existing_recordings_need_no_authentication(monkeypatch, reference):
    existing = {key: reference[key] for key in ("fingerprint", "scenarioId", "asOf")}
    existing["cases"] = [record(item, reference) for item in reference["cases"]]
    class Existing:
        @staticmethod
        def exists():
            return True
        @staticmethod
        def read_text(**kwargs):
            return json.dumps(existing)
    monkeypatch.setattr(capture, "OUTPUT", Existing())
    monkeypatch.setattr(capture, "atomic_write", lambda path, payload: None)
    monkeypatch.setattr(capture, "cached_token", lambda *args: pytest.fail("No token is needed"))
    assert capture.main([]) == 0
