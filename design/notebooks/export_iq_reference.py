"""Export the IQ walkthrough from existing seed tables and ontology bindings.

Two independent local resolutions: explicit table lookups and traversal of edges
instantiated from RELATIONSHIPS. These are repository examples, not Fabric captures.
Run from the root: python -m design.notebooks.export_iq_reference
"""
import csv
import hashlib
import json

from fabric._shared.paths import ARTIFACTS, ROOT
from fabric.ontology.deploy_ontology import ENTITIES, RELATIONSHIPS

OUTPUT = ROOT / "app" / "src" / "data" / "iq-reference.generated.json"
TABLES = ("dim_media_owner", "dim_campaign", "dim_advertiser", "dim_market", "fact_plan")
EDGES = ("CampaignBooksMediaOwner", "CampaignForAdvertiser", "CampaignInMarket")


def read_tables():
    tables = {}
    for name in TABLES:
        with (ARTIFACTS / f"{name}.csv").open(encoding="utf-8", newline="") as stream:
            tables[name] = list(csv.DictReader(stream))
    return tables


def index(rows, key):
    result = {}
    for row in rows:
        if not row[key] or row[key] in result:
            raise ValueError(f"Missing or duplicate {key}: {row[key]!r}")
        result[row[key]] = row
    return result


def result_row(owner, campaign, advertiser, market):
    return {
        "mediaOwnerId": owner["media_owner_id"], "mediaOwner": owner["media_owner_name"],
        "campaignId": campaign["campaign_id"], "campaign": campaign["campaign_name"],
        "advertiserId": advertiser["advertiser_id"], "advertiser": advertiser["advertiser_name"],
        "marketId": market["market_id"], "market": market["market_name"],
        "quarter": campaign["quarter"],
    }


def ordered(rows):
    return sorted(rows, key=lambda r: (r["mediaOwnerId"], r["quarter"], r["campaignId"]))


def tabular_scope(tables):
    owners = index(tables["dim_media_owner"], "media_owner_id")
    campaigns = index(tables["dim_campaign"], "campaign_id")
    advertisers = index(tables["dim_advertiser"], "advertiser_id")
    markets = index(tables["dim_market"], "market_id")
    pairs = {(r["campaign_id"], r["media_owner_id"]) for r in tables["fact_plan"]}
    return ordered([
        result_row(owners[oid], campaigns[cid],
                   advertisers[campaigns[cid]["advertiser_id"]],
                   markets[campaigns[cid]["market_id"]])
        for cid, oid in pairs
    ])


def ontology_scope(tables):
    nodes = {}
    for name, table, keys, _columns in ENTITIES:
        if table in tables:
            if len(keys) != 1:
                raise ValueError(f"Reference resolver requires a single key for {name}")
            nodes[name] = index(tables[table], keys[0])
    edges = {}
    for name, source, target, table, source_keys, target_keys in RELATIONSHIPS:
        if name not in EDGES:
            continue
        if len(source_keys) != 1 or len(target_keys) != 1:
            raise ValueError(f"Reference resolver requires single keys for {name}")
        pairs = {(r[source_keys[0]], r[target_keys[0]]) for r in tables[table]}
        for src, dst in pairs:
            if src not in nodes[source] or dst not in nodes[target]:
                raise ValueError(f"Dangling {name} relationship: {src} -> {dst}")
        edges[name] = pairs

    def targets(name, source):
        return [dst for src, dst in edges[name] if src == source]

    rows = []
    for cid, oid in edges["CampaignBooksMediaOwner"]:
        for aid in targets("CampaignForAdvertiser", cid):
            for mid in targets("CampaignInMarket", cid):
                rows.append(result_row(nodes["MediaOwner"][oid], nodes["Campaign"][cid],
                                       nodes["Advertiser"][aid], nodes["Market"][mid]))
    return ordered(rows)


def build_reference():
    tables = read_tables()
    tabular = tabular_scope(tables)
    ontology = ontology_scope(tables)
    if tabular != ontology:
        raise ValueError("Tabular and ontology-binding scopes disagree")
    relations = [
        {"name": name, "from": source, "to": target, "table": table,
         "fromKey": source_keys[0], "toKey": target_keys[0]}
        for name, source, target, table, source_keys, target_keys in RELATIONSHIPS
        if name in EDGES
    ]
    fingerprint = hashlib.sha256(
        json.dumps({"tables": tables, "relations": relations}, sort_keys=True).encode()
    ).hexdigest()
    return {
        "kind": "repository",
        "description": "Local reference computed from seed CSVs and ontology bindings. Not a Fabric query capture.",
        "fingerprint": fingerprint,
        "relations": relations,
        "tabular": tabular,
        "ontology": ontology,
    }


def main():
    reference = build_reference()
    OUTPUT.write_text(json.dumps(reference, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"IQ reference: {len(reference['tabular'])} distinct campaign/media-owner pairs; both paths agree.")


if __name__ == "__main__":
    main()
