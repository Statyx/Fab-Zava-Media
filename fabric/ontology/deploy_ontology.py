#!/usr/bin/env python3
"""
Deploy the Zava Media ontology (Fabric IQ) over the batch Lakehouse.

7 entity types + 9 relationships. NonTimeSeries (Lakehouse) bindings for the media
star schema, PLUS a TimeSeries (Eventhouse/KQL) binding on Campaign (pacing_events),
so one semantic layer carries both the booked/billed history and the live pacing.

This is the layer that makes the demo's question answerable in one hop:
  "which advertiser over-delivered, and does their contract let us rebate it?"
The graph answers the WHO/WHICH (relationships); the semantic model answers the
HOW MUCH (measures); Foundry answers the WHAT DOES THE CONTRACT SAY.

NOTE: deploying via REST does NOT populate the child Graph Model — run deploy_graph.py
afterwards (build + push the graph definition + RefreshGraph). See graph-agent.
"""
import os, sys, json, base64, hashlib, uuid
from fabric._shared.platform_env import bootstrap
bootstrap()

import requests
from fabric._shared.helpers import (get_fabric_token, fabric_headers, load_config, load_state,
                     save_state, poll_operation, find_item, print_step)

VT = {"string": "String", "int64": "BigInt", "double": "Double",
      "datetime": "DateTime", "bool": "Boolean"}

# (name, lakehouse_table, key_cols[], cols=[(col, type)])
# deploy_graph.py imports this tuple shape unchanged — do not add a 5th element.
ENTITIES = [
    ("Advertiser", "dim_advertiser", ["advertiser_id"], [
        ("advertiser_id", "string"), ("advertiser_name", "string"), ("legal_entity", "string"),
        ("industry", "string"), ("hq_market_id", "string"), ("account_director", "string")]),
    ("Brand", "dim_brand", ["brand_id"], [
        ("brand_id", "string"), ("brand_name", "string"), ("advertiser_id", "string"),
        ("category", "string")]),
    ("Campaign", "dim_campaign", ["campaign_id"], [
        ("campaign_id", "string"), ("campaign_name", "string"), ("advertiser_id", "string"),
        ("brand_id", "string"), ("market_id", "string"), ("objective", "string"),
        ("quarter", "string"), ("start_date", "string"), ("end_date", "string"),
        ("status", "string"), ("planned_budget_eur", "double")]),
    ("Market", "dim_market", ["market_id"], [
        ("market_id", "string"), ("market_name", "string"), ("country_code", "string"),
        ("currency", "string"), ("region", "string")]),
    ("Channel", "dim_channel", ["channel_id"], [
        ("channel_id", "string"), ("channel_name", "string"), ("channel_group", "string"),
        ("measurement_unit", "string"), ("rate_card_cpm_eur", "double"),
        ("is_grp_channel", "bool")]),
    ("MediaOwner", "dim_media_owner", ["media_owner_id"], [
        ("media_owner_id", "string"), ("media_owner_name", "string"), ("owner_type", "string"),
        ("channels_sold", "string"), ("primary_channel_id", "string"),
        ("agency_discount_pct", "double"), ("rebate_pct", "double")]),
    ("Invoice", "fact_billing", ["invoice_id"], [
        ("invoice_id", "string"), ("campaign_id", "string"), ("media_owner_id", "string"),
        ("month", "string"), ("gross_amount_eur", "double"), ("net_amount_eur", "double"),
        ("rebate_amount_eur", "double"), ("net_net_amount_eur", "double"),
        ("invoice_status", "string"), ("invoice_date", "string")]),
]

# The default display name is the first non-key string column, which is wrong for
# Invoice (it would show the campaign id). Override explicitly where that happens.
DISPLAY_PROPERTY = {"Invoice": "invoice_id"}

# (name, source_entity, target_entity, fk_table, source_key_cols[], target_fk_cols[])
# BOTH column lists are columns OF fk_table: the one identifying the source, and the
# one holding the target's key. Getting this backwards yields an empty graph, not an error.
RELATIONSHIPS = [
    ("AdvertiserHasBrand",      "Advertiser", "Brand",      "dim_brand",       ["advertiser_id"],   ["brand_id"]),
    ("BrandHasCampaign",        "Brand",      "Campaign",   "dim_campaign",    ["brand_id"],        ["campaign_id"]),
    ("CampaignForAdvertiser",   "Campaign",   "Advertiser", "dim_campaign",    ["campaign_id"],     ["advertiser_id"]),
    ("CampaignInMarket",        "Campaign",   "Market",     "dim_campaign",    ["campaign_id"],     ["market_id"]),
    ("CampaignUsesChannel",     "Campaign",   "Channel",    "fact_plan",       ["campaign_id"],     ["channel_id"]),
    ("CampaignBooksMediaOwner", "Campaign",   "MediaOwner", "fact_plan",       ["campaign_id"],     ["media_owner_id"]),
    ("InvoiceForCampaign",      "Invoice",    "Campaign",   "fact_billing",    ["invoice_id"],      ["campaign_id"]),
    ("InvoiceFromMediaOwner",   "Invoice",    "MediaOwner", "fact_billing",    ["invoice_id"],      ["media_owner_id"]),
    ("MediaOwnerSellsChannel",  "MediaOwner", "Channel",    "dim_media_owner", ["media_owner_id"],  ["primary_channel_id"]),
]

# TimeSeries bindings: live Eventhouse pacing onto the Campaign entity, so the ontology
# unifies NonTimeSeries (booked/billed) + TimeSeries (actual pacing) in one layer.
# name -> (kql_table, timestamp_col, entity_key_col, [(metric_col, valueType), ...])
TIMESERIES = {
    "Campaign": ("pacing_events", "timestamp", "campaign_id",
                 [("impressions_delta", "BigInt"), ("spend_delta", "Double"),
                  ("pacing_index", "Double")]),
}


def det_guid(seed: str) -> str:
    return str(uuid.UUID(bytes=hashlib.md5(seed.encode("utf-8")).digest()))


def b64(obj) -> str:
    return base64.b64encode(json.dumps(obj).encode("utf-8")).decode("ascii")


def build_parts(workspace_id, lakehouse_id, ontology_name, kql_db_id, cluster_uri, kql_db_name):
    et_id, prop_id, key_prop = {}, {}, {}
    for i, (name, table, keys, cols) in enumerate(ENTITIES):
        eid = str(1001 + i); et_id[name] = eid
        base = 10000 + i * 100
        for j, (col, _t) in enumerate(cols):
            prop_id[(name, col)] = str(base + 1 + j)
        key_prop[name] = [prop_id[(name, k)] for k in keys]

    parts = []
    platform = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "Ontology", "displayName": ontology_name,
                     "description": f"Zava Media knowledge graph ({len(ENTITIES)} entities, "
                                    f"{len(RELATIONSHIPS)} relationships, live pacing on Campaign)."},
        "config": {"version": "2.0", "logicalId": det_guid("ONT-ZAVA-MEDIA-logicalId")},
    }
    parts.append({"path": ".platform", "payload": b64(platform), "payloadType": "InlineBase64"})
    parts.append({"path": "definition.json", "payload": b64({}), "payloadType": "InlineBase64"})

    for name, table, keys, cols in ENTITIES:
        eid = et_id[name]
        i = int(eid) - 1001
        if name in DISPLAY_PROPERTY:
            disp_col = DISPLAY_PROPERTY[name]
        else:
            non_key_str = [c for c, t in cols if t == "string" and c not in keys]
            disp_col = non_key_str[0] if non_key_str else keys[0]
        properties = [{"id": prop_id[(name, c)], "name": c, "redefines": None,
                       "baseTypeNamespaceType": None, "valueType": VT[t]} for c, t in cols]

        ts_props, ts_binding_part = [], None
        if name in TIMESERIES:
            kql_table, ts_col, key_col, metrics = TIMESERIES[name]
            tsb = 40000 + i * 100
            ts_props = [{"id": str(tsb + 1), "name": ts_col, "redefines": None,
                         "baseTypeNamespaceType": None, "valueType": "DateTime"}]
            pbinds = [{"sourceColumnName": key_col, "targetPropertyId": prop_id[(name, key_col)]},
                      {"sourceColumnName": ts_col, "targetPropertyId": str(tsb + 1)}]
            for j, (mcol, vt) in enumerate(metrics):
                pid = str(tsb + 2 + j)
                ts_props.append({"id": pid, "name": mcol, "redefines": None,
                                 "baseTypeNamespaceType": None, "valueType": vt})
                pbinds.append({"sourceColumnName": mcol, "targetPropertyId": pid})
            ts_guid = det_guid(f"TimeSeries-{eid}")
            ts_binding = {"id": ts_guid, "dataBindingConfiguration": {
                "dataBindingType": "TimeSeries", "timestampColumnName": ts_col,
                "propertyBindings": pbinds,
                "sourceTableProperties": {"sourceType": "KustoTable", "workspaceId": workspace_id,
                                          "itemId": kql_db_id, "clusterUri": cluster_uri,
                                          "databaseName": kql_db_name, "sourceTableName": kql_table}}}
            ts_binding_part = {"path": f"EntityTypes/{eid}/DataBindings/{ts_guid}.json",
                               "payload": b64(ts_binding), "payloadType": "InlineBase64"}

        entity_def = {
            "id": eid, "namespace": "usertypes", "baseEntityTypeId": None, "name": name,
            "entityIdParts": key_prop[name], "displayNamePropertyId": prop_id[(name, disp_col)],
            "namespaceType": "Custom", "visibility": "Visible",
            "properties": properties, "timeseriesProperties": ts_props,
        }
        parts.append({"path": f"EntityTypes/{eid}/definition.json",
                      "payload": b64(entity_def), "payloadType": "InlineBase64"})

        bind_guid = det_guid(f"NonTimeSeries-{eid}")
        binding = {"id": bind_guid, "dataBindingConfiguration": {
            "dataBindingType": "NonTimeSeries",
            "propertyBindings": [{"sourceColumnName": c, "targetPropertyId": prop_id[(name, c)]}
                                 for c, _t in cols],
            "sourceTableProperties": {"sourceType": "LakehouseTable", "workspaceId": workspace_id,
                                      "itemId": lakehouse_id, "sourceTableName": table,
                                      "sourceSchema": "dbo"}}}
        parts.append({"path": f"EntityTypes/{eid}/DataBindings/{bind_guid}.json",
                      "payload": b64(binding), "payloadType": "InlineBase64"})
        if ts_binding_part:
            parts.append(ts_binding_part)

    for k, (rname, src, tgt, fk_table, src_keys, tgt_fks) in enumerate(RELATIONSHIPS):
        rid = str(3001 + k)
        rel_def = {"namespace": "usertypes", "id": rid, "name": rname, "namespaceType": "Custom",
                   "source": {"entityTypeId": et_id[src]}, "target": {"entityTypeId": et_id[tgt]}}
        parts.append({"path": f"RelationshipTypes/{rid}/definition.json",
                      "payload": b64(rel_def), "payloadType": "InlineBase64"})
        ctx_guid = det_guid(f"Ctx-{rid}")
        src_refs = [{"sourceColumnName": col, "targetPropertyId": key_prop[src][i]}
                    for i, col in enumerate(src_keys)]
        tgt_refs = [{"sourceColumnName": col, "targetPropertyId": key_prop[tgt][i]}
                    for i, col in enumerate(tgt_fks)]
        ctx = {"id": ctx_guid,
               "dataBindingTable": {"workspaceId": workspace_id, "itemId": lakehouse_id,
                                    "sourceTableName": fk_table, "sourceSchema": "dbo",
                                    "sourceType": "LakehouseTable"},
               "sourceKeyRefBindings": src_refs, "targetKeyRefBindings": tgt_refs}
        parts.append({"path": f"RelationshipTypes/{rid}/Contextualizations/{ctx_guid}.json",
                      "payload": b64(ctx), "payloadType": "InlineBase64"})

    return parts


def main():
    cfg = load_config(); state = load_state()
    api = cfg["fabric_api_base"]; ws = state["workspace_id"]; lh = state["lakehouse_id"]
    name = cfg["ontology_name"]
    kql_db_id = state["kql_database_id"]; cluster_uri = state["query_service_uri"]
    # The KQL database Fabric actually created — resolved by deploy_eventhouse.py.
    kql_db_name = state.get("kql_db_name") or cfg["eventhouse_name"]
    token = get_fabric_token(); headers = fabric_headers(token)

    print(f"Deploying Ontology '{name}' — {len(ENTITIES)} entities, "
          f"{len(RELATIONSHIPS)} relationships, {len(TIMESERIES)} TimeSeries binding(s)")

    print_step(1, 4, "Build definition parts")
    parts = build_parts(ws, lh, name, kql_db_id, cluster_uri, kql_db_name)
    print(f"   {len(parts)} parts")

    print_step(2, 4, "Create or find Ontology item")
    ont_id = state.get("ontology_id")
    if ont_id:
        try:
            find_item(token, api, ws, name, "Ontology")
        except RuntimeError:
            ont_id = None
    if not ont_id:
        try:
            ont_id = find_item(token, api, ws, name, "Ontology")["id"]
        except RuntimeError:
            r = requests.post(f"{api}/workspaces/{ws}/items", headers=headers,
                              json={"displayName": name, "type": "Ontology",
                                    "description": "Zava Media knowledge graph (Fabric IQ)"},
                              timeout=60)
            if r.status_code in (200, 201):
                ont_id = r.json()["id"]
            elif r.status_code == 202:
                op = r.headers.get("x-ms-operation-id")
                if op: poll_operation(token, api, op)
                ont_id = find_item(token, api, ws, name, "Ontology")["id"]
            else:
                raise RuntimeError(f"Create Ontology failed ({r.status_code}): {r.text[:400]}")
        print(f"   id: {ont_id}")
    else:
        print(f"   reusing: {ont_id}")

    print_step(3, 4, "Push full definition (updateDefinition)")
    resp = requests.post(f"{api}/workspaces/{ws}/items/{ont_id}/updateDefinition",
                         headers=headers, json={"definition": {"parts": parts}}, timeout=120)
    if resp.status_code in (200, 201):
        print("   accepted")
    elif resp.status_code == 202:
        op = resp.headers.get("x-ms-operation-id")
        if op: poll_operation(token, api, op)
        print("   accepted (async)")
    else:
        raise RuntimeError(f"updateDefinition failed ({resp.status_code}): {resp.text[:600]}")

    print_step(4, 4, "Persist state")
    state["ontology_id"] = ont_id; save_state(state)
    print(f"   ontology_id = {ont_id}")
    print("\nOK. Next: deploy_graph.py — the ontology alone leaves the Graph Model EMPTY.")


if __name__ == "__main__":
    main()
