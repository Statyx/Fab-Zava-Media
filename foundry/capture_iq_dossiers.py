#!/usr/bin/env python3
"""Capture the two existing IQ dossiers without deploying or changing CLI authentication.

Run ``python -m foundry.capture_iq_dossiers`` from the repository root. The recorder
uses only the cached CLI identity for config.yaml's explicit tenant. Each saved case
has independently verified DAX measurements, structured graph membership and a real
supervisor response. A partial run exits nonzero and never manufactures missing answers.
Use ``--force`` to refresh compatible recordings; prior frozen answers are untouched.
"""
import argparse, base64, binascii, json, math, os, re, subprocess, sys, time, uuid
from fabric._shared.platform_env import bootstrap
bootstrap()

from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

from fabric._shared import platform_env
from fabric._shared.paths import CONFIG_FILE, ROOT, STATE_FILE
from foundry.capture_frozen_answers import ask_supervisor

DATA = ROOT / "app" / "src" / "data"
REFERENCE = DATA / "iq-dossier-reference.generated.json"
OUTPUT = DATA / "iq-dossier-capture.generated.json"
AUDIENCES = {
    "fabric": "https://api.fabric.microsoft.com",
    "powerbi": "https://analysis.windows.net/powerbi/api",
    "foundry": "https://ai.azure.com",
}
TOLERANCE = 0.0005


class CaptureError(RuntimeError):
    """A failed precondition or incomplete source; never eligible for a recording."""


def sanitized(message: str) -> str:
    message = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*",
                     "[redacted token]", str(message))
    message = re.sub(r"(?i)Bearer\s+\S+", "Bearer [redacted]", message)
    message = re.sub(r'(?i)("?(?:accessToken|access_token)"?\s*[:=]\s*)"?[^"\s,}]+',
                     r'\1[redacted]', message)
    return message[:700]


def validate_token(token: str, tenant: str, now: float | None = None) -> datetime:
    """Inspect CLI-issued claims in memory, not as a substitute for server validation."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("not a JWT")
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        if str(uuid.UUID(claims["tid"])) != str(uuid.UUID(tenant)):
            raise CaptureError("Cached token belongs to a different tenant; refusing it.")
        expiry = claims["exp"]
        if type(expiry) not in (int, float) or not math.isfinite(expiry):
            raise ValueError("invalid expiration")
        if expiry <= (time.time() if now is None else now) + 60:
            raise CaptureError("Cached token is expired or expires within 60 seconds.")
        return datetime.fromtimestamp(expiry, timezone.utc)
    except (ValueError, KeyError, TypeError, AttributeError, binascii.Error, OverflowError) as exc:
        raise CaptureError("The CLI token has invalid tenant/expiration claims.") from exc


def cached_token(tenant: str, audience: str) -> str:
    try:
        tenant = str(uuid.UUID(tenant))
    except (ValueError, TypeError, AttributeError) as exc:
        raise CaptureError("config.yaml must contain a valid tenant_id.") from exc
    if audience not in AUDIENCES.values():
        raise CaptureError("Unsupported token audience.")
    # Azure CLI rejects --subscription together with --tenant. Never change the
    # default account to work around that restriction: fail closed on auth errors.
    command = ["az", "account", "get-access-token", "--tenant", tenant,
               "--resource", audience, "--output", "json", "--only-show-errors"]
    try:
        result = subprocess.run(
            command,
            shell=platform_env.AZ_NEEDS_SHELL, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CaptureError(f"Cached authentication failed: {type(exc).__name__}.") from exc
    if result.returncode:
        raise CaptureError(
            f"Cached authentication failed for {audience}: "
            f"{sanitized(result.stderr.strip()) or 'Azure CLI returned an error.'}"
        )
    try:
        token = json.loads(result.stdout)["accessToken"]
    except (ValueError, KeyError, TypeError) as exc:
        raise CaptureError("Azure CLI did not return a usable access token.") from exc
    expiry = validate_token(token, tenant)
    print(f"  Auth OK: {audience}; project tenant verified; expires {expiry.isoformat()}",
          flush=True)
    return token


def dossier_prompt(item: dict, as_of: str) -> str:
    """Pinned against the actual TypeScript dossierPrompt by the recorder tests."""
    return (
        f"Review the fictional Zava demo at the scenario date {as_of}, after 2026-Q3 has closed. "
        f"For {item['advertiser']} ({item['advertiserId']}) in {item['market']} "
        f"({item['marketId']}) during {item['quarter']}, "
        "read [Planned Impressions], [Delivered Impressions] and [Delivery vs Plan %] from the semantic model. "
        "Verify the campaign scope using the published relationships; expected candidate IDs to check are "
        f"{', '.join(item['campaignIds'])}. "
        "Retrieve the signed master agreement, cite the applicable delivery-variance articles and their assessment period. "
        "Explain the treatment supported by those sources. Do not infer a monetary credit amount without verified contracted channel rates. "
        "Do not assume an approval, issuance or any work progress; no collaboration system is connected for this question. "
        "Say explicitly if evidence is missing or disagrees with the candidate scope. Use the data and contracts tools."
    )


def queries(item: dict) -> tuple[str, str]:
    for key in ("advertiserId", "marketId", "quarter"):
        if not re.fullmatch(r"[A-Za-z0-9-]+", item[key]):
            raise CaptureError("Invalid scenario identifier.")
    filters = (
        f'TREATAS({{"{item["advertiserId"]}"}}, dim_advertiser[advertiser_id]),\n'
        f'    TREATAS({{"{item["marketId"]}"}}, dim_market[market_id]),\n'
        f'    TREATAS({{"{item["quarter"]}"}}, dim_campaign[quarter])'
    )
    measures = ('"planned", [Planned Impressions],\n'
                '    "delivered", [Delivered Impressions],\n'
                '    "variance", [Delivery vs Plan %]')
    # Total measures are evaluated directly, not averaged from campaign percentages.
    # Advertiser filters follow the published campaign -> brand -> advertiser model path.
    dax = f"""EVALUATE
VAR campaigns = SUMMARIZECOLUMNS(
    dim_campaign[campaign_id],
    {filters},
    {measures}
)
VAR totals = SUMMARIZECOLUMNS(
    {filters},
    {measures}
)
RETURN UNION(
    SELECTCOLUMNS(campaigns, "rowType", "campaign", "campaignId", dim_campaign[campaign_id],
        "planned", [planned], "delivered", [delivered], "variance", [variance]),
    SELECTCOLUMNS(totals, "rowType", "total", "campaignId", "",
        "planned", [planned], "delivered", [delivered], "variance", [variance])
)"""
    gql = f"""MATCH (c:Campaign)-[:CampaignForAdvertiser]->(a:Advertiser), (c)-[:CampaignInMarket]->(m:Market)
WHERE a.advertiser_id = '{item["advertiserId"]}' AND m.market_id = '{item["marketId"]}' AND c.quarter = '{item["quarter"]}'
RETURN DISTINCT c.campaign_id AS campaignId"""
    return dax, gql


def reject_data_errors(value, source: str) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.lower() in ("error", "errors") and nested:
                raise CaptureError(f"{source} returned a data error: {sanitized(json.dumps(nested))}")
            reject_data_errors(nested, source)
    elif isinstance(value, list):
        for nested in value:
            reject_data_errors(nested, source)


def post_query(url: str, token: str, body: dict, source: str) -> dict:
    response = requests.post(
        url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body, timeout=120,
    )
    if response.status_code != 200:
        raise CaptureError(
            f"{source} HTTP {response.status_code}: {sanitized(response.text)}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise CaptureError(f"{source} did not return JSON.") from exc
    if not isinstance(payload, dict):
        raise CaptureError(f"{source} did not return an object.")
    reject_data_errors(payload, source)
    return payload


def measured_facts(raw: dict) -> dict:
    facts = {key: raw.get(key) for key in ("planned", "delivered", "variance")}
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in facts.values()):
        raise CaptureError("DAX measurements are missing or non-finite.")
    if facts["planned"] <= 0 or facts["delivered"] < 0 or abs(
        facts["delivered"] / facts["planned"] - 1 - facts["variance"]
    ) > TOLERANCE:
        raise CaptureError("DAX measurements are inconsistent.")
    return facts


def verify_facts(facts: dict, item: dict) -> None:
    measured_facts(facts)
    if (facts["planned"] != item["facts"]["planned"] or
            facts["delivered"] != item["facts"]["delivered"] or
            abs(facts["variance"] - item["facts"]["variance"]) > TOLERANCE):
        raise CaptureError("Live DAX facts differ from the reference.")


def scope_ids(values: list) -> list[str]:
    if not isinstance(values, list) or not values or any(
        not isinstance(value, str) or not re.fullmatch(r"CMP-[0-9]+", value) for value in values
    ):
        raise CaptureError("Source returned an empty or invalid campaign scope.")
    return sorted(set(values))


def dax_evidence(payload: dict, item: dict) -> tuple[dict, list[str]]:
    reject_data_errors(payload, "DAX")
    try:
        results = payload["results"]
        if len(results) != 1 or len(results[0]["tables"]) != 1:
            raise CaptureError("DAX must return exactly one result table.")
        rows = results[0]["tables"][0]["rows"]
        if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
            raise CaptureError("DAX returned no valid rows.")
        rows = [{key.strip("[]"): value for key, value in row.items()} for row in rows]
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise CaptureError("DAX returned an invalid result table.") from exc
    totals = [r for r in rows if r.get("rowType") == "total"]
    campaigns = [r for r in rows if r.get("rowType") == "campaign"]
    if len(totals) != 1 or len(totals) + len(campaigns) != len(rows):
        raise CaptureError("DAX is missing its unique total or contains unknown rows.")
    ids = scope_ids([r.get("campaignId") for r in campaigns])
    if len(ids) != len(campaigns) or ids != scope_ids(item["campaignIds"]):
        raise CaptureError("DAX campaign IDs differ from the reference or contain duplicates.")
    facts = measured_facts(totals[0])
    verify_facts(facts, item)
    grouped = [measured_facts(r) for r in campaigns]
    if any(sum(r[key] for r in grouped) != facts[key] for key in ("planned", "delivered")):
        raise CaptureError("DAX campaign measurements disagree with the measured total.")
    return facts, ids


def graph_evidence(payload: dict, expected: list[str]) -> list[str]:
    reject_data_errors(payload, "Graph")
    try:
        if payload["status"]["code"] != "00000" or payload["result"]["kind"] != "TABLE":
            raise CaptureError("Graph did not return a successful TABLE result.")
        rows = payload["result"]["data"]
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise CaptureError("Graph returned invalid structured rows.")
        ids = scope_ids([row.get("campaignId") for row in rows])
    except (KeyError, TypeError) as exc:
        raise CaptureError("Graph did not return the documented structured result.") from exc
    if ids != scope_ids(expected):
        raise CaptureError("Graph campaign IDs disagree with DAX/reference scope.")
    return ids


def verify_answer(item: dict, text: str, tools: list, citations: list) -> None:
    if not isinstance(text, str) or len(text.strip()) < 100:
        raise CaptureError("Foundry returned no substantive response.")
    if not isinstance(tools, list) or not all(isinstance(t, str) and t.strip() for t in tools):
        raise CaptureError("Foundry returned invalid tools.")
    if not any(re.search(r"contract|file_search", t, re.I) for t in tools) or not any(
        re.search(r"dataagent|fabric", t, re.I) for t in tools
    ):
        raise CaptureError("Foundry must actually invoke both data and contract sources.")
    if not isinstance(citations, list) or any(
        not isinstance(c, dict) or not isinstance(c.get("label"), str) or not c["label"].strip()
        or ("detail" in c and not isinstance(c["detail"], str)) for c in citations
    ):
        raise CaptureError("Foundry returned malformed citations.")
    plain = re.sub(r"\s+", " ", re.sub(r"[*_]", "", text)).lower()
    unavailable = (
        r"(?:could not|cannot|can't|unable to|couldn't|not able to).{0,80}"
        r"(?:retrieve|access|read|find|verify|complete|confirm)|"
        r"(?:contract|agreement|data|evidence|scope).{0,35}(?:unavailable|not available|missing)|"
        r"(?:scope|campaign.{0,5}ids).{0,50}(?:disagree|mismatch)|"
        r"(?:refuse|refusal|i cannot assist)"
    )
    if re.search(unavailable, plain):
        raise CaptureError("Foundry reports unavailable or contradictory evidence.")
    market = re.escape(item["market"].lower())
    if item["marketId"] == "MKT-UK":
        market = rf"(?:{market}|\buk\b|\bgb\b)"
    if (item["advertiser"].lower() not in plain or not re.search(market, plain)
            or not re.search(r"2026[- ]q3|q3(?: of)? 2026", plain)):
        raise CaptureError("Foundry did not establish the correct advertiser, market and quarter.")
    cited = plain + " " + json.dumps(citations).lower()
    if item["contract"]["reference"].lower() not in cited and item["contract"]["file"].lower() not in cited:
        raise CaptureError("Foundry did not cite the applicable master agreement.")
    if item["id"] == "contoso-es":
        if not all(re.search(pattern, plain) for pattern in (
            r"6\.2", r"credit", r"45", r"10\s*(?:%|percent)", r"6\.4",
        )):
            raise CaptureError("Foundry did not establish Contoso's applicable articles and clause terms.")
        if re.search(
            r"(?:no|not entitled to (?:a )?).{0,20}(?:credit|compensation).{0,20}(?:due|required|owed)|"
            r"(?:credit|compensation) (?:is |are )?(?:excluded|not due)", plain,
        ):
            raise CaptureError("Foundry contradicts Contoso's contract.")
    elif item["id"] == "litware-uk":
        if not re.search(r"6\.[12]", plain) or not re.search(
            r"no.{0,25}(?:credit|compensation)|(?:credit|compensation).{0,20}(?:excluded|not due)|not entitled",
            plain,
        ):
            raise CaptureError("Foundry did not establish Litware's exclusion articles.")
        if re.search(r"(?:must|shall|should) issue (?:a )?(?:compensation )?credit|requires (?:a )?(?:compensation )?credit", plain):
            raise CaptureError("Foundry contradicts Litware's contract.")
    else:
        raise CaptureError("Unsupported dossier case.")


def atomic_write(path: Path, payload: dict) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    pending = path.with_name(f".{path.name}.{uuid.uuid4().hex}.pending")
    try:
        with pending.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
    finally:
        if pending.exists():
            pending.unlink()


def validate_record(record: dict, item: dict, as_of: str) -> None:
    try:
        if record["id"] != item["id"] or record["prompt"] != dossier_prompt(item, as_of):
            raise CaptureError("Recorded prompt or case is stale.")
        if (not isinstance(record["dax"], str) or not record["dax"].strip()
                or not isinstance(record["gql"], str) or not record["gql"].strip()):
            raise CaptureError("Recorded source queries are missing.")
        if tuple(record[key] for key in ("dax", "gql")) != queries(item):
            raise CaptureError("Recorded source queries are stale.")
        when = datetime.fromisoformat(record["capturedAt"].replace("Z", "+00:00"))
        if when.tzinfo is None:
            raise CaptureError("Recorded capture time needs a timezone.")
        if type(record["seconds"]) not in (int, float) or not math.isfinite(record["seconds"]) or record["seconds"] < 0:
            raise CaptureError("Invalid recorded duration.")
        verify_facts(record["facts"], item)
        if scope_ids(record["campaignIds"]) != scope_ids(item["campaignIds"]):
            raise CaptureError("Recorded campaign scope is stale.")
        verify_answer(item, record["text"], record["toolsFired"], record["citations"])
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise CaptureError("Recorded evidence is incomplete or malformed.") from exc


def capture_case(item: dict, reference: dict, state: dict, tokens: dict) -> dict:
    start = time.monotonic()
    dax, gql = queries(item)
    workspace, model, graph = (state[k] for k in ("workspace_id", "semantic_model_id", "graph_model_id"))
    dax_payload = post_query(
        f"https://api.powerbi.com/v1.0/myorg/groups/{workspace}/datasets/{model}/executeQueries",
        tokens["powerbi"], {"queries": [{"query": dax}], "serializerSettings": {"includeNulls": True}}, "DAX",
    )
    facts, dax_ids = dax_evidence(dax_payload, item)
    print(f"  {item['id']}: DAX facts and exact campaign scope verified.", flush=True)
    graph_payload = post_query(
        f"{AUDIENCES['fabric']}/v1/workspaces/{workspace}/graphModels/{graph}/executeQuery?beta=true",
        tokens["fabric"], {"query": gql}, "Graph",
    )
    ids = graph_evidence(graph_payload, dax_ids)
    print(f"  {item['id']}: structured graph matches DAX/reference; asking Foundry.", flush=True)
    prompt = dossier_prompt(item, reference["asOf"])
    text, tools, citations, _, _ = ask_supervisor(
        state["foundry_endpoint"], state["foundry_supervisor_agent"], prompt, tokens["foundry"]
    )
    verify_answer(item, text, tools, citations)
    record = {
        "id": item["id"], "prompt": prompt, "capturedAt": datetime.now(timezone.utc).isoformat(),
        "seconds": round(time.monotonic() - start, 1), "text": text,
        "toolsFired": tools, "citations": citations, "facts": facts,
        "campaignIds": ids, "dax": dax, "gql": gql,
    }
    validate_record(record, item, reference["asOf"])
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="refresh complete compatible captures")
    args = parser.parse_args(argv)
    failures = 0
    try:
        reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
        payload = {key: reference[key] for key in ("fingerprint", "scenarioId", "asOf")}
        payload["cases"] = []
        if OUTPUT.exists():
            existing = json.loads(OUTPUT.read_text(encoding="utf-8"))
            if all(existing.get(key) == payload[key] for key in ("fingerprint", "scenarioId", "asOf")):
                for record in existing.get("cases", []):
                    item = next((c for c in reference["cases"] if c["id"] == record.get("id")), None)
                    if item is None:
                        raise CaptureError("Capture contains an unknown case.")
                    validate_record(record, item, reference["asOf"])
                    if any(c["id"] == record["id"] for c in payload["cases"]):
                        raise CaptureError("Capture contains duplicate cases.")
                    payload["cases"].append(record)
            else:
                print("Discarding incompatible dossier evidence; source fingerprint/scenario changed.")
        atomic_write(OUTPUT, payload)
        todo = [item for item in reference["cases"] if args.force or not any(
            c["id"] == item["id"] for c in payload["cases"]
        )]
        if not todo:
            print("Both compatible dossier recordings are complete; no cloud calls needed.")
            return 0
        config = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        for key in ("workspace_id", "semantic_model_id", "graph_model_id",
                    "foundry_endpoint", "foundry_supervisor_agent"):
            if not isinstance(state.get(key), str) or not state[key].strip():
                raise CaptureError(f"state.json is missing {key}; no resources will be created.")
        tokens = {name: cached_token(config.get("tenant_id"), audience)
                  for name, audience in AUDIENCES.items()}
        for item in todo:
            try:
                record = capture_case(item, reference, state, tokens)
                payload["cases"] = [c for c in payload["cases"] if c["id"] != item["id"]] + [record]
                atomic_write(OUTPUT, payload)
                print(f"COMPLETE {item['id']}: saved verified evidence ({record['seconds']}s).", flush=True)
            except (CaptureError, requests.RequestException, RuntimeError, ValueError, OSError) as exc:
                failures += 1
                print(f"INCOMPLETE {item['id']}: {sanitized(str(exc))}", file=sys.stderr, flush=True)
        print(f"Captured {len(payload['cases'])}/{len(reference['cases'])} complete cases; {failures} failed attempts.")
        return 1 if failures or len(payload["cases"]) != len(reference["cases"]) else 0
    except (CaptureError, OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        print(f"INCOMPLETE capture: {sanitized(str(exc))}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
