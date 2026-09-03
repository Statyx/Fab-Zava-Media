#!/usr/bin/env python3
"""
Create the Fabric Data Agent 'Zava_Media_Analyst' — the Fabric half of the demo.

Two sources:
  1. ONT_Zava_Media (Ontology, GQL)      -> WHO / WHICH: advertiser -> brand -> campaign ->
                                            channel / media owner / invoice traversals.
  2. SM_Zava_Media (Semantic Model, DAX) -> HOW MUCH: planned vs delivered, rebates, billing.

It deliberately does NOT answer contractual questions. Whether an over-delivery entitles
an advertiser to compensation is a CLAUSE, retrieved by the Foundry orchestrator
(Zava-Media-Agent) from design/contracts/. Keeping that boundary sharp is the whole point
of the demo: a number nobody can audit is worth nothing, and a clause quoted without the
number behind it is worth nothing either.

The exact datasource `type` for an ontology source is not documented, so we deploy with
type "ontology" then read it back (getDefinition) to confirm the service accepted it.
Published by default — a draft-only agent is invisible to the portal AND to Foundry.

Usage:
  python -m fabric.data_agent.deploy_data_agent            # create/update + publish
  python -m fabric.data_agent.deploy_data_agent --delete   # delete the agent
"""
import os, sys, base64, json, uuid, time, argparse
from fabric._shared.platform_env import bootstrap
bootstrap()

import requests
from fabric._shared.helpers import (load_config, load_state, save_state, get_fabric_token,
                     fabric_headers, poll_operation, b64encode_json, print_step)

AGENT_DESC = ("Dual-source media agency agent: campaign/advertiser/media-owner relationships "
              "via the ONT_Zava_Media ontology (GQL) + plan-vs-delivery and billing figures "
              "via the SM_Zava_Media semantic model (DAX). Does not answer contract questions.")

AI_INSTRUCTIONS = """You are the Zava Media Analyst, the data agent of a media agency.
You answer questions about media plans, actual delivery and supplier billing across advertisers,
brands, campaigns, markets, channels and media owners, by querying TWO data sources. ALWAYS answer
by querying a source — NEVER from general knowledge or assumptions. If a query returns nothing, say
so explicitly rather than guessing.

## Two data sources — pick the right one for each question
1. ONT_Zava_Media (Ontology, GQL) — RELATIONSHIPS and TRAVERSALS.
   Use it for: which brands an advertiser owns, which campaigns ran for a brand, which channels and
   media owners a campaign booked, which invoices belong to a campaign or a media owner — anything
   about HOW entities connect.
2. SM_Zava_Media (Semantic Model, DAX) — NUMBERS and AGGREGATES.
   Use it for: planned vs delivered impressions, over/under-delivery percentages, GRP, spend, CPM,
   CTR, gross/net/net-net billing, rebates, disputed invoices, and any count / sum / average /
   ranking. ALWAYS use the existing DAX measures — never recompute from raw columns.

Routing rule: if the question asks for a NUMBER, a percentage or a ranking, use the Semantic Model.
If it asks WHICH entities are connected to what, use the Ontology. For "find then explain"
questions, get the number from the Semantic Model first, then traverse the graph for the context.

## Source 1 — Ontology (GQL): entities (node label : properties)
- Advertiser (advertiser_id, advertiser_name, legal_entity, industry, hq_market_id, account_director)
- Brand (brand_id, brand_name, advertiser_id, category)
- Campaign (campaign_id, campaign_name, advertiser_id, brand_id, market_id, objective, quarter,
  start_date, end_date, status, planned_budget_eur)
- Market (market_id, market_name, country_code, currency, region)
- Channel (channel_id, channel_name, channel_group, measurement_unit, rate_card_cpm_eur, is_grp_channel)
- MediaOwner (media_owner_id, media_owner_name, owner_type, channels_sold, primary_channel_id,
  agency_discount_pct, rebate_pct)
- Invoice (invoice_id, campaign_id, media_owner_id, month, gross_amount_eur, net_amount_eur,
  rebate_amount_eur, net_net_amount_eur, invoice_status, invoice_date)

### Relationships (edge label, direction matters)
- Advertiser -[AdvertiserHasBrand]-> Brand
- Brand -[BrandHasCampaign]-> Campaign
- Campaign -[CampaignForAdvertiser]-> Advertiser
- Campaign -[CampaignInMarket]-> Market
- Campaign -[CampaignUsesChannel]-> Channel
- Campaign -[CampaignBooksMediaOwner]-> MediaOwner
- Invoice -[InvoiceForCampaign]-> Campaign
- Invoice -[InvoiceFromMediaOwner]-> MediaOwner
- MediaOwner -[MediaOwnerSellsChannel]-> Channel

In GQL the node label is the entity name and the edge label is the relationship name.
Traverse an edge in REVERSE with <-[:Name]- when you need the other direction.
Do NOT ask this source for delivery or billing FIGURES — use the semantic model for every number.

## Source 2 — Semantic Model (DAX): key measures (ALWAYS reuse, never recompute)
- Plan: [Planned Budget (EUR)], [Planned Impressions], [Planned GRP]
- Delivery: [Delivered Impressions], [Delivered Clicks], [Net Spend (EUR)], [Delivered GRP], [CTR %],
  [Effective CPM (EUR)]
- Plan vs delivery: [Delivery vs Plan %] (the primary answer to any over/under-delivery question),
  [Delivery Ratio], [Impression Gap], [GRP Delivery %], [Over-delivered Campaigns],
  [Under-delivered Campaigns], [Budget Consumption %]
- Billing: [Gross Billed (EUR)], [Net Billed (EUR)], [Rebate Amount (EUR)], [Net Net Billed (EUR)],
  [Rebate % of Gross], [Total Invoices], [Disputed Invoices], [Disputed Amount (EUR)],
  [Billing vs Spend Gap (EUR)]
- Counts: [Total Advertisers], [Total Brands], [Total Campaigns], [Active Campaigns],
  [Total Markets], [Total Channels], [Total Media Owners]
Group and filter with dim_advertiser[advertiser_name], dim_brand[brand_name],
dim_campaign[campaign_name], dim_campaign[quarter], dim_market[market_name],
dim_channel[channel_name], dim_media_owner[media_owner_name], fact_billing[invoice_status].
Use EVALUATE with SUMMARIZECOLUMNS / ROW / TOPN.

## Domain rules that change the answer
- GRP and impressions are DIFFERENT UNITS. Never add them. Only use GRP measures where
  dim_channel[is_grp_channel] is TRUE (TV, DOOH, Audio).
- The advertiser is reached through the brand (Advertiser -> Brand -> Campaign), never directly
  from the campaign — the direct path is deliberately not part of the model.
- Over-delivery is [Delivery vs Plan %] > 0, under-delivery is < 0. State the planned and the
  delivered figure alongside the percentage so the reader can check it.
- dim_media_owner[rebate_pct] is what the MEDIA OWNER grants the AGENCY. It is NOT what the agency
  owes the advertiser. Never present it as a client entitlement.

## HARD BOUNDARY — what you must not answer
This model contains NO contractual terms. You cannot say whether a client is entitled to
compensation, a make-good, a rebate pass-through or an audit. If asked, state the measured figure,
then say plainly that the contractual entitlement is not in your data and must come from the
contract itself. Do not speculate, do not infer a clause from a rebate percentage.

## Response format
- Lead with a direct one-line answer, figures as digits (e.g. "+12.0%", "48,300,000 impressions").
- Give the planned and delivered numbers whenever you give a percentage.
- Then a short bullet list of the entities involved (IDs and the attributes that matter).
- For multi-hop answers, briefly state the path you traversed.
- Be concise — your reader is an account director preparing a client conversation."""

# ── Ontology few-shots (GQL) ────────────────────────────────────────
FEWSHOTS = [
    ("Which brands belong to Contoso Mobility?",
     "MATCH (a:Advertiser {advertiser_name:'Contoso Mobility'})-[:AdvertiserHasBrand]->(b:Brand) "
     "RETURN b.brand_id, b.brand_name, b.category"),
    ("Which campaigns ran for the brand Contoso EV?",
     "MATCH (b:Brand {brand_name:'Contoso EV'})-[:BrandHasCampaign]->(c:Campaign) "
     "RETURN c.campaign_id, c.campaign_name, c.quarter, c.status"),
    ("Which campaigns did Contoso Mobility run in Spain in 2026-Q3?",
     "MATCH (a:Advertiser {advertiser_id:'ADV-001'})-[:AdvertiserHasBrand]->(b:Brand)"
     "-[:BrandHasCampaign]->(c:Campaign)-[:CampaignInMarket]->(m:Market {market_id:'MKT-ES'}) "
     "WHERE c.quarter = '2026-Q3' RETURN c.campaign_id, c.campaign_name, c.planned_budget_eur"),
    ("Which channels did campaign CMP-0001 book?",
     "MATCH (c:Campaign {campaign_id:'CMP-0001'})-[:CampaignUsesChannel]->(ch:Channel) "
     "RETURN DISTINCT ch.channel_id, ch.channel_name, ch.channel_group, ch.measurement_unit"),
    ("Which media owners did campaign CMP-0001 buy from?",
     "MATCH (c:Campaign {campaign_id:'CMP-0001'})-[:CampaignBooksMediaOwner]->(o:MediaOwner) "
     "RETURN DISTINCT o.media_owner_id, o.media_owner_name, o.owner_type"),
    ("Which invoices belong to campaign CMP-0001?",
     "MATCH (i:Invoice)-[:InvoiceForCampaign]->(c:Campaign {campaign_id:'CMP-0001'}) "
     "RETURN i.invoice_id, i.month, i.gross_amount_eur, i.invoice_status"),
    ("Which media owner issued invoice INV-000123?",
     "MATCH (i:Invoice {invoice_id:'INV-000123'})-[:InvoiceFromMediaOwner]->(o:MediaOwner) "
     "RETURN o.media_owner_name, o.owner_type, o.rebate_pct"),
    ("Which advertiser is campaign CMP-0001 for?",
     "MATCH (c:Campaign {campaign_id:'CMP-0001'})-[:CampaignForAdvertiser]->(a:Advertiser) "
     "RETURN a.advertiser_name, a.legal_entity, a.account_director"),
    ("Which channel does Meridian TV primarily sell?",
     "MATCH (o:MediaOwner {media_owner_name:'Meridian TV'})-[:MediaOwnerSellsChannel]->(ch:Channel) "
     "RETURN ch.channel_name, ch.measurement_unit, ch.rate_card_cpm_eur"),
    ("Which media owners did Litware Retail buy from in the UK?",
     "MATCH (a:Advertiser {advertiser_id:'ADV-004'})-[:AdvertiserHasBrand]->(b:Brand)"
     "-[:BrandHasCampaign]->(c:Campaign)-[:CampaignInMarket]->(m:Market {market_id:'MKT-UK'}) "
     "MATCH (c)-[:CampaignBooksMediaOwner]->(o:MediaOwner) "
     "RETURN DISTINCT o.media_owner_name"),
    ("How many campaigns does each advertiser have?",
     "MATCH (a:Advertiser)-[:AdvertiserHasBrand]->(b:Brand)-[:BrandHasCampaign]->(c:Campaign) "
     "RETURN a.advertiser_name, count(c) AS campaigns ORDER BY campaigns DESC"),
    ("Which disputed invoices exist and for which campaigns?",
     "MATCH (i:Invoice)-[:InvoiceForCampaign]->(c:Campaign) WHERE i.invoice_status = 'Disputed' "
     "RETURN i.invoice_id, i.gross_amount_eur, c.campaign_name"),
    ("List every advertiser and its contracting legal entity.",
     "MATCH (a:Advertiser) RETURN a.advertiser_id, a.advertiser_name, a.legal_entity, a.industry"),
]

# ── Semantic model few-shots (DAX) ──────────────────────────────────
SM_FEWSHOT_PAIRS = [
    ("What is the over-delivery for Contoso Mobility in Spain in 2026-Q3?",
     'EVALUATE\nSUMMARIZECOLUMNS(\n'
     '    dim_advertiser[advertiser_name],\n'
     '    dim_market[market_name],\n'
     '    dim_campaign[quarter],\n'
     '    FILTER(ALL(dim_advertiser[advertiser_name]), dim_advertiser[advertiser_name] = "Contoso Mobility"),\n'
     '    FILTER(ALL(dim_market[market_name]), dim_market[market_name] = "Spain"),\n'
     '    FILTER(ALL(dim_campaign[quarter]), dim_campaign[quarter] = "2026-Q3"),\n'
     '    "Planned", [Planned Impressions],\n'
     '    "Delivered", [Delivered Impressions],\n'
     '    "Delivery vs Plan", [Delivery vs Plan %]\n)'),
    ("Which advertiser over-delivered the most?",
     'EVALUATE\nTOPN(1, ADDCOLUMNS(VALUES(dim_advertiser[advertiser_name]), '
     '"Gap", [Delivery vs Plan %]), [Gap], DESC)'),
    ("Show planned vs delivered impressions by advertiser and market.",
     'EVALUATE\nSUMMARIZECOLUMNS(dim_advertiser[advertiser_name], dim_market[market_name],\n'
     '    "Planned", [Planned Impressions], "Delivered", [Delivered Impressions],\n'
     '    "Delivery vs Plan", [Delivery vs Plan %])'),
    ("How many campaigns over-delivered and how many under-delivered?",
     'EVALUATE\nROW("Over", [Over-delivered Campaigns], "Under", [Under-delivered Campaigns])'),
    ("What rebate was actually applied, in euros and as a share of gross?",
     'EVALUATE\nROW("Rebate EUR", [Rebate Amount (EUR)], "Rebate pct of gross", [Rebate % of Gross])'),
    ("What is the effective CPM per channel?",
     'EVALUATE\nSUMMARIZECOLUMNS(dim_channel[channel_name], "eCPM", [Effective CPM (EUR)], '
     '"Delivered", [Delivered Impressions])'),
    ("Which media owner has the largest disputed amount?",
     'EVALUATE\nTOPN(1, ADDCOLUMNS(VALUES(dim_media_owner[media_owner_name]), '
     '"Disputed", [Disputed Amount (EUR)]), [Disputed], DESC)'),
    ("What is the billing versus spend gap for Litware Retail?",
     'EVALUATE\nSUMMARIZECOLUMNS(dim_advertiser[advertiser_name],\n'
     '    FILTER(ALL(dim_advertiser[advertiser_name]), dim_advertiser[advertiser_name] = "Litware Retail"),\n'
     '    "Net spend", [Net Spend (EUR)], "Net net billed", [Net Net Billed (EUR)],\n'
     '    "Gap", [Billing vs Spend Gap (EUR)])'),
    ("What is the GRP delivery against plan by market?",
     'EVALUATE\nSUMMARIZECOLUMNS(dim_market[market_name], "Planned GRP", [Planned GRP],\n'
     '    "Delivered GRP", [Delivered GRP], "GRP delivery", [GRP Delivery %])'),
    ("What is the budget consumption per campaign for 2026-Q3?",
     'EVALUATE\nSUMMARIZECOLUMNS(dim_campaign[campaign_name],\n'
     '    FILTER(ALL(dim_campaign[quarter]), dim_campaign[quarter] = "2026-Q3"),\n'
     '    "Planned budget", [Planned Budget (EUR)], "Net spend", [Net Spend (EUR)],\n'
     '    "Consumption", [Budget Consumption %])'),
]


def build_sm_elements():
    """Selected tables / columns / measures exposed to the agent for DAX."""
    def _col(name, desc):
        return {"id": None, "display_name": name, "type": "semantic_model.column",
                "is_selected": True, "description": desc, "children": []}

    def _meas(name, desc):
        return {"id": None, "display_name": name, "type": "semantic_model.measure",
                "is_selected": True, "description": desc, "children": []}

    def _table(name, desc, children):
        return {"id": None, "display_name": name, "type": "semantic_model.table",
                "is_selected": True, "description": desc, "children": children}

    return [
        _table("dim_advertiser", "Advertisers under contract with the agency", [
            _col("advertiser_id", "Advertiser code"),
            _col("advertiser_name", "Advertiser name"),
            _col("legal_entity", "Contracting legal entity"),
            _col("industry", "Industry"),
            _col("account_director", "Agency account director"),
            _meas("Total Advertisers", "Number of advertisers"),
        ]),
        _table("dim_brand", "Brands belonging to an advertiser", [
            _col("brand_id", "Brand code"), _col("brand_name", "Brand name"),
            _col("category", "Product category"),
            _meas("Total Brands", "Number of brands"),
        ]),
        _table("dim_campaign", "Media campaigns", [
            _col("campaign_id", "Campaign code"), _col("campaign_name", "Campaign name"),
            _col("objective", "Objective"), _col("quarter", "Fiscal quarter, e.g. 2026-Q3"),
            _col("status", "Campaign status"),
            _col("planned_budget_eur", "Campaign-level planned budget"),
            _meas("Total Campaigns", "Number of campaigns"),
            _meas("Active Campaigns", "Campaigns currently live"),
        ]),
        _table("dim_market", "Markets the agency buys media in", [
            _col("market_id", "Market code"), _col("market_name", "Market name"),
            _col("country_code", "ISO country code"), _col("currency", "Local currency"),
            _col("region", "Region grouping"),
            _meas("Total Markets", "Number of markets"),
        ]),
        _table("dim_channel", "Media channels; GRP channels are traded in rating points", [
            _col("channel_id", "Channel code"), _col("channel_name", "Channel name"),
            _col("channel_group", "Online or Offline"),
            _col("measurement_unit", "Trading unit"),
            _col("rate_card_cpm_eur", "Rate-card CPM"),
            _col("is_grp_channel", "TRUE when traded in GRP"),
            _meas("Total Channels", "Number of channels"),
        ]),
        _table("dim_media_owner", "Media owners the agency buys from", [
            _col("media_owner_id", "Media owner code"),
            _col("media_owner_name", "Media owner name"),
            _col("owner_type", "Owner type"),
            _col("agency_discount_pct", "Discount the owner grants the agency"),
            _col("rebate_pct", "Volume rebate the owner grants the agency"),
            _meas("Total Media Owners", "Number of media owners"),
        ]),
        _table("dim_date", "Calendar", [
            _col("date_key", "Date key YYYY-MM-DD"), _col("year", "Year"),
            _col("quarter", "Calendar quarter"), _col("month_name", "Month name"),
        ]),
        _table("fact_plan", "The booked plan — denominator of every delivery ratio", [
            _col("month", "Plan month YYYY-MM"),
            _meas("Planned Budget (EUR)", "Total booked budget"),
            _meas("Planned Impressions", "Total booked impressions"),
            _meas("Planned GRP", "Total booked GRP"),
        ]),
        _table("fact_delivery", "What was actually delivered, daily", [
            _meas("Delivered Impressions", "Total impressions delivered"),
            _meas("Delivered Clicks", "Total clicks"),
            _meas("Net Spend (EUR)", "Total net spend"),
            _meas("Delivered GRP", "Total GRP delivered"),
            _meas("CTR %", "Clicks over impressions"),
            _meas("Effective CPM (EUR)", "Net spend per thousand delivered impressions"),
            _meas("Delivery vs Plan %", "Over (positive) or under (negative) delivery vs plan"),
            _meas("Delivery Ratio", "Delivered over planned as a ratio"),
            _meas("Impression Gap", "Absolute over/under delivery in impressions"),
            _meas("GRP Delivery %", "Over/under delivery on GRP channels"),
            _meas("Over-delivered Campaigns", "Campaigns more than 5% above plan"),
            _meas("Under-delivered Campaigns", "Campaigns more than 5% below plan"),
            _meas("Budget Consumption %", "Net spend against booked budget"),
        ]),
        _table("fact_billing", "Supplier invoices: gross -> net -> net-net", [
            _col("invoice_id", "Invoice number"), _col("month", "Billing month YYYY-MM"),
            _col("invoice_status", "Paid, Open or Disputed"),
            _meas("Gross Billed (EUR)", "Gross invoiced amount"),
            _meas("Net Billed (EUR)", "After agency discount"),
            _meas("Rebate Amount (EUR)", "Volume rebate actually applied"),
            _meas("Net Net Billed (EUR)", "After discount and rebate"),
            _meas("Rebate % of Gross", "Rebate applied as a share of gross"),
            _meas("Total Invoices", "Number of invoices"),
            _meas("Disputed Invoices", "Invoices in dispute"),
            _meas("Disputed Amount (EUR)", "Gross amount in dispute"),
            _meas("Billing vs Spend Gap (EUR)", "Invoiced minus delivery-accounted spend"),
        ]),
    ]


def b64(obj):
    return b64encode_json(obj)


def find_agent(api, ws, h, name):
    r = requests.get(f"{api}/workspaces/{ws}/items?type=DataAgent", headers=h, timeout=60)
    if r.status_code == 200:
        for it in r.json().get("value", []):
            if it.get("displayName") == name:
                return it["id"]
    # Fall back to an unfiltered list — ?type= can 404 in some workspaces.
    r = requests.get(f"{api}/workspaces/{ws}/items", headers=h, timeout=60)
    if r.status_code == 200:
        for it in r.json().get("value", []):
            if it.get("type") == "DataAgent" and it.get("displayName") == name:
                return it["id"]
    return None


def build_parts(ws, agent_name, ont_id, ont_name, sm_id, sm_name):
    ont_folder = f"ontology-{ont_name}"
    sm_folder = f"semantic-model-{sm_name}"
    SCH = "https://developer.microsoft.com/json-schemas/fabric/item/dataAgent/definition"
    data_agent = {"$schema": f"{SCH}/dataAgent/2.1.0/schema.json"}
    stage = {"$schema": f"{SCH}/stageConfiguration/1.0.0/schema.json",
             "aiInstructions": AI_INSTRUCTIONS}

    ont_ds = {
        "$schema": f"{SCH}/dataSource/1.0.0/schema.json",
        "artifactId": ont_id, "workspaceId": ws, "displayName": ont_name, "type": "ontology",
        "userDescription": ("Media knowledge graph: 7 entities (Advertiser, Brand, Campaign, "
                            "Market, Channel, MediaOwner, Invoice) and 9 relationships covering "
                            "who booked what, with which media owner, on which channel, and which "
                            "invoice covers it."),
        "dataSourceInstructions": (
            "Use for RELATIONSHIPS and TRAVERSALS (GQL). Node label = entity name, edge label = "
            "relationship name. The advertiser is reached through the brand: "
            "(a:Advertiser)-[:AdvertiserHasBrand]->(b:Brand)-[:BrandHasCampaign]->(c:Campaign). "
            "Traverse in reverse with <-[:Name]-. Do NOT use this source for delivery, spend or "
            "billing FIGURES — use the semantic model for every number."),
    }
    ont_fs = {"$schema": f"{SCH}/fewShots/1.0.0/schema.json",
              "fewShots": [{"id": str(uuid.uuid4()), "question": q, "query": gql}
                           for q, gql in FEWSHOTS]}

    sm_ds = {
        "$schema": f"{SCH}/dataSource/1.0.0/schema.json",
        "artifactId": sm_id, "workspaceId": ws, "displayName": sm_name, "type": "semantic_model",
        "dataSourceInstructions": (
            "Use for ALL numbers: planned vs delivered impressions and GRP, over/under-delivery "
            "percentages, spend, CPM, CTR, gross/net/net-net billing, rebates, disputed invoices, "
            "and any count/sum/average/ranking. ALWAYS reuse the existing DAX measures; never "
            "recompute from raw columns. [Delivery vs Plan %] is the primary answer to any "
            "over/under-delivery question — always quote [Planned Impressions] and "
            "[Delivered Impressions] alongside it so the reader can check the arithmetic. "
            "Never add GRP to impressions. Group with dim_advertiser[advertiser_name], "
            "dim_market[market_name], dim_campaign[quarter]; filter one advertiser with "
            "dim_advertiser[advertiser_name] = \"Contoso Mobility\"."),
        "elements": build_sm_elements(),
    }
    sm_fs = {"$schema": f"{SCH}/fewShots/1.0.0/schema.json",
             "fewShots": [{"id": str(uuid.uuid4()), "question": q, "query": dax}
                          for q, dax in SM_FEWSHOT_PAIRS]}

    s = b64(stage)
    ont_ds_b, ont_fs_b = b64(ont_ds), b64(ont_fs)
    sm_ds_b, sm_fs_b = b64(sm_ds), b64(sm_fs)
    pub = b64({"$schema": f"{SCH}/publishInfo/1.0.0/schema.json",
               "description": f"{agent_name} -- dual-source (ontology + semantic model) -- "
                              f"published {time.strftime('%Y-%m-%d')}"})

    def _p(path, payload):
        return {"path": path, "payload": payload, "payloadType": "InlineBase64"}

    # The published/ tree is NOT optional: an agent with only a draft/ tree is invisible
    # in the portal and cannot be attached as a Foundry tool.
    return [
        _p("Files/Config/data_agent.json", b64(data_agent)),
        _p("Files/Config/draft/stage_config.json", s),
        _p(f"Files/Config/draft/{ont_folder}/datasource.json", ont_ds_b),
        _p(f"Files/Config/draft/{ont_folder}/fewshots.json", ont_fs_b),
        _p(f"Files/Config/draft/{sm_folder}/datasource.json", sm_ds_b),
        _p(f"Files/Config/draft/{sm_folder}/fewshots.json", sm_fs_b),
        _p("Files/Config/publish_info.json", pub),
        _p("Files/Config/published/stage_config.json", s),
        _p(f"Files/Config/published/{ont_folder}/datasource.json", ont_ds_b),
        _p(f"Files/Config/published/{ont_folder}/fewshots.json", ont_fs_b),
        _p(f"Files/Config/published/{sm_folder}/datasource.json", sm_ds_b),
        _p(f"Files/Config/published/{sm_folder}/fewshots.json", sm_fs_b),
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delete", action="store_true")
    args = ap.parse_args()

    cfg = load_config(); st = load_state()
    api = cfg["fabric_api_base"]; ws = st["workspace_id"]
    agent_name = cfg.get("data_agent_name", "Zava_Media_Analyst")
    ont_id = st.get("ontology_id"); ont_name = cfg["ontology_name"]
    sm_id = st.get("semantic_model_id")
    sm_name = cfg.get("semantic_model_name", "SM_Zava_Media")
    if not ont_id:
        print("Ontology not deployed. Run deploy_ontology.py first."); sys.exit(1)
    if not sm_id:
        print("Semantic model not deployed. Run deploy_semantic_model.py first."); sys.exit(1)
    token = get_fabric_token(); h = fabric_headers(token)

    if args.delete:
        aid = st.get("data_agent_id") or find_agent(api, ws, h, agent_name)
        if aid:
            requests.delete(f"{api}/workspaces/{ws}/items/{aid}", headers=h, timeout=60)
            print(f"deleted {aid}")
            st.pop("data_agent_id", None); save_state(st)
        else:
            print("no agent to delete")
        return

    print_step(1, 3, f"Create/Update Data Agent '{agent_name}' "
                     f"(sources = ontology {ont_name} + semantic model {sm_name})")
    parts = build_parts(ws, agent_name, ont_id, ont_name, sm_id, sm_name)
    aid = st.get("data_agent_id") or find_agent(api, ws, h, agent_name)
    if aid:
        print(f"   updating: {aid}  ({len(parts)} parts)")
        r = requests.post(f"{api}/workspaces/{ws}/items/{aid}/updateDefinition", headers=h,
                          json={"definition": {"parts": parts}}, timeout=120)
        if r.status_code == 202:
            op = r.headers.get("x-ms-operation-id")
            if op: poll_operation(token, api, op)
        elif r.status_code not in (200, 201):
            raise RuntimeError(f"updateDefinition failed ({r.status_code}): {r.text[:600]}")
        print(f"   updated ({r.status_code})")
    else:
        print(f"   creating ({len(parts)} parts)")
        r = requests.post(f"{api}/workspaces/{ws}/items", headers=h,
                          json={"displayName": agent_name, "description": AGENT_DESC,
                                "type": "DataAgent", "definition": {"parts": parts}}, timeout=120)
        if r.status_code in (200, 201):
            aid = r.json()["id"]
        elif r.status_code == 202:
            op = r.headers.get("x-ms-operation-id")
            if op: poll_operation(token, api, op)
            aid = find_agent(api, ws, h, agent_name)
        else:
            raise RuntimeError(f"create failed ({r.status_code}): {r.text[:600]}")
        print(f"   created: {aid}")

    print_step(2, 3, "Persist state")
    st["data_agent_id"] = aid; save_state(st)
    print(f"   data_agent_id = {aid}")

    print_step(3, 3, "Readback (confirm the datasource types were accepted)")
    data = {}
    try:
        rr = requests.post(f"{api}/workspaces/{ws}/items/{aid}/getDefinition", headers=h, timeout=30)
        if rr.status_code == 200:
            data = rr.json()
        elif rr.status_code == 202:
            op = rr.headers.get("x-ms-operation-id")
            status = None
            for _ in range(20):
                time.sleep(1.5)
                status = requests.get(f"{api}/operations/{op}", headers=h,
                                      timeout=20).json().get("status")
                if status in ("Succeeded", "Failed"):
                    break
            if status == "Succeeded":
                # /result can hang on api.fabric.microsoft.com (SSL read) — guard it hard
                g = requests.get(f"{api}/operations/{op}/result", headers=h,
                                 timeout=20, allow_redirects=False)
                if g.status_code == 200:
                    data = g.json()
    except Exception as e:
        print(f"   (readback skipped: {type(e).__name__})")
    parts_rb = data.get("definition", {}).get("parts", [])
    if parts_rb:
        published = [p["path"] for p in parts_rb if "/published/" in p["path"]]
        print(f"   {len(parts_rb)} parts, {len(published)} under published/")
        for p in parts_rb:
            if p["path"].endswith("datasource.json") and "/draft/" in p["path"]:
                d = json.loads(base64.b64decode(p["payload"]).decode())
                print(f"   datasource.type = {d.get('type')}  artifactId = {d.get('artifactId')}")
        if not published:
            print("   ⚠  no published/ parts came back — the agent will be invisible to Foundry.")
    else:
        print("   (no definition returned — verify in the portal)")

    print(f"\nOK. '{agent_name}' is deployed. Foundry connects to THIS agent as a tool; "
          f"the orchestrator '{cfg.get('foundry', {}).get('orchestrator_agent_name', 'Zava-Media-Agent')}' "
          f"adds the contract half.")


if __name__ == "__main__":
    main()
