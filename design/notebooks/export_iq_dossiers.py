"""Generate reproducible dossier inputs from existing facts, contracts and simulated notes.

This is repository evidence, never an agent recording or a Fabric capture.
Run: python -m design.notebooks.export_iq_dossiers
"""
import csv
import hashlib
import json
import re
from datetime import date

from fabric._shared.paths import ARTIFACTS, CONTRACTS, ROOT
from design.notebooks.export_iq_reference import build_reference

OUTPUT = ROOT / "app" / "src" / "data" / "iq-dossier-reference.generated.json"
WORK_NOTES = ROOT / "artifacts" / "iq_context" / "work-notes.json"
WEB_NOTES = ROOT / "artifacts" / "iq_context" / "web-notes.json"
WEB_OUTPUT = ROOT / "app" / "src" / "data" / "iq-web-context.generated.json"
CASES = (
    ("contoso-es", "ADV-001", "MKT-ES", "ADV-001-contoso-mobility.md", "credit"),
    ("litware-uk", "ADV-004", "MKT-UK", "ADV-004-litware-retail.md", "excluded"),
)


def rows(table):
    with (ARTIFACTS / f"{table}.csv").open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def article(text, number):
    found = re.search(
        rf"\*\*{re.escape(number)}(?:\*\*|\s|\.\s)(.*?)(?=\n\*\*\d+\.\d+(?:\*\*|\s)|\n##|\Z)",
        text, re.S,
    )
    if not found:
        raise ValueError(f"Missing contract article {number}")
    return found.group(0).strip()


def build_dossiers():
    work = json.loads(WORK_NOTES.read_text(encoding="utf-8"))
    if work["simulated"] is not True or any(n["simulated"] is not True for n in work["notes"]):
        raise ValueError("Work context must remain explicitly simulated")
    as_of = date.fromisoformat(work["asOf"])
    if as_of <= date(2026, 9, 30):
        raise ValueError("This scenario requires a closed Q3")
    tables = {t: rows(t) for t in ("dim_campaign", "dim_advertiser", "dim_brand", "dim_market", "fact_plan", "fact_delivery")}
    advertisers = {r["advertiser_id"]: r for r in tables["dim_advertiser"]}
    brands = {r["brand_id"]: r for r in tables["dim_brand"]}
    markets = {r["market_id"]: r for r in tables["dim_market"]}
    graph = build_reference()
    cases = []
    for cid, aid, mid, filename, treatment in CASES:
        campaigns = [c for c in tables["dim_campaign"] if c["advertiser_id"] == aid
                     and c["market_id"] == mid and c["quarter"] == "2026-Q3"]
        if not campaigns or any(brands[c["brand_id"]]["advertiser_id"] != aid for c in campaigns):
            raise ValueError("Campaign, brand and advertiser scopes disagree")
        ids = sorted(c["campaign_id"] for c in campaigns)
        graph_ids = sorted({r["campaignId"] for r in graph["ontology"]
                            if r["advertiserId"] == aid and r["marketId"] == mid and r["quarter"] == "2026-Q3"})
        if ids != graph_ids:
            raise ValueError("Tabular and ontology scopes disagree")
        planned = sum(int(r["planned_impressions"]) for r in tables["fact_plan"] if r["campaign_id"] in ids)
        delivered = sum(int(r["impressions"]) for r in tables["fact_delivery"] if r["campaign_id"] in ids)
        if planned <= 0:
            raise ValueError("Planned impressions must be positive")
        contract = (CONTRACTS / filename).read_text(encoding="utf-8")
        articles = ("5.2", "6.1", "6.2", "6.4") if treatment == "credit" else ("6.1", "6.2", "6.3")
        cases.append({
            "id": cid, "advertiserId": aid, "advertiser": advertisers[aid]["advertiser_name"],
            "marketId": mid, "market": markets[mid]["market_name"], "quarter": "2026-Q3",
            "campaignIds": ids, "campaigns": [{"id": c["campaign_id"], "name": c["campaign_name"],
                "brand": brands[c["brand_id"]]["brand_name"]} for c in campaigns],
            "facts": {"planned": planned, "delivered": delivered, "variance": delivered / planned - 1},
            "contract": {"file": filename, "reference": f"ZM-{aid}-2026", "treatment": treatment,
                "fingerprint": hashlib.sha256(contract.encode()).hexdigest(),
                "articles": [{"number": n, "text": article(contract, n)} for n in articles]},
        })
    for note in work["notes"]:
        case = next((c for c in cases if c["id"] == note["caseId"]), None)
        if case is None or any(note[k] != case[k] for k in ("advertiserId", "marketId", "quarter")):
            raise ValueError("Simulated note has an unmatched case scope")
        if not date(2026, 9, 30) < date.fromisoformat(note["date"]) <= as_of:
            raise ValueError("Simulated note is outside the closed-quarter scenario")
    payload = {"scenarioId": work["scenarioId"], "asOf": work["asOf"], "kind": "repository",
               "cases": cases, "workNotes": work["notes"], "scopeFingerprint": graph["fingerprint"]}
    payload["fingerprint"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return payload


def build_web_context(dossiers):
    """Keep fictional web context separate from the real Fabric/Foundry capture fingerprint."""
    web = json.loads(WEB_NOTES.read_text(encoding="utf-8"))
    if web["simulated"] is not True or any(web[k] != dossiers[k] for k in ("scenarioId", "asOf")):
        raise ValueError("Web context must be simulated and match the dossier scenario")
    if not web["notes"]:
        raise ValueError("Expected fictional web notes")
    ids = set()
    cases = set()
    for note in web["notes"]:
        if note["simulated"] is not True:
            raise ValueError("Web notes must remain explicitly simulated")
        for key in ("id", "caseId", "source", "headline", "summary", "meetingPrompt", "publishedOn"):
            if not isinstance(note.get(key), str) or not note[key].strip():
                raise ValueError(f"Missing web note field: {key}")
        case = next((c for c in dossiers["cases"] if c["id"] == note["caseId"]), None)
        if case is None or any(note[k] != case[k] for k in ("advertiserId", "marketId", "quarter")):
            raise ValueError("Web note has an unmatched case scope")
        if note["id"] in ids or note["caseId"] in cases:
            raise ValueError("Duplicate web note or case")
        ids.add(note["id"])
        cases.add(note["caseId"])
        if date.fromisoformat(note["publishedOn"]) > date.fromisoformat(web["asOf"]):
            raise ValueError("Web note was published after the scenario date")
    if cases != {c["id"] for c in dossiers["cases"]}:
        raise ValueError("Each dossier must have a fictional web note")
    web["fingerprint"] = hashlib.sha256(json.dumps(web, sort_keys=True).encode()).hexdigest()
    return web


def main():
    payload = build_dossiers()
    web = build_web_context(payload)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    WEB_OUTPUT.write_text(json.dumps(web, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print("Exported two repository dossiers; Work IQ and Web IQ notes remain simulated.")


if __name__ == "__main__":
    main()
