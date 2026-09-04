#!/usr/bin/env python3
"""
Deploy Semantic Model SM_Zava_Media — Direct Lake over ZavaMediaLH.

Star schema: 7 media dimensions + 3 facts (plan / delivery / billing), all Delta.
The measures are deliberately narrow and auditable: every number the data agent
quotes must be reproducible by hand from two columns.

THE MEASURE THAT CARRIES THE DEMO is [Delivery vs Plan %] — delivered impressions
against planned impressions. Sliced by advertiser x market x quarter it exposes the
over-delivery that the contract clause then has to be applied to. Its companion is
[Rebate % of Gross]: Fabric states what was ACTUALLY rebated; Foundry retrieves what
the contract SAYS should be rebated; the orchestrator compares the two. Keep that
split — the semantic model must never encode a contractual rate.

The live pacing stream is NOT in this model. It stays in the Eventhouse and is reached
through the ontology's TimeSeries binding — see deploy_ontology.py.
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import json, uuid
from pathlib import Path
import requests

from fabric._shared.helpers import (load_config, load_state, save_state,
                     get_fabric_token, fabric_headers,
                     b64encode_json, poll_operation, find_item, print_step)

API_BASE = None


def _tag():
    return str(uuid.uuid4())


def _col(name, data_type, desc="", fmt="", hidden=False, summarize_none=False):
    col = {"name": name, "dataType": data_type, "sourceColumn": name, "lineageTag": _tag()}
    if desc: col["description"] = desc
    if fmt: col["formatString"] = fmt
    if hidden: col["isHidden"] = True
    if summarize_none: col["summarizeBy"] = "none"
    return col


def _measure(name, expr, desc="", fmt="", folder=""):
    m = {"name": name, "expression": expr.split("\n"), "lineageTag": _tag()}
    if desc: m["description"] = desc
    if fmt: m["formatString"] = fmt
    if folder: m["displayFolder"] = folder
    return m


def _partition(table_name):
    return {"name": table_name, "mode": "directLake",
            "source": {"type": "entity", "entityName": table_name,
                       "expressionSource": "DatabaseQuery"}}


PCT = "0.0%;-0.0%;0.0%"
EUR = "\\€#,0"
NUM = "#,0"


def build_model_bim(config, state):
    tables = []

    # ── dim_advertiser ───────────────────────────────────────────
    tables.append({
        "name": "dim_advertiser", "lineageTag": _tag(),
        "description": "Advertisers under contract with the agency (the contracting legal entity)",
        "columns": [
            _col("advertiser_id", "string", "Advertiser code", summarize_none=True),
            _col("advertiser_name", "string", "Advertiser display name"),
            _col("legal_entity", "string", "Contracting legal entity (matches the contract header)"),
            _col("industry", "string", "Industry sector"),
            _col("hq_market_id", "string", "HQ market FK", hidden=True, summarize_none=True),
            _col("account_director", "string", "Agency account director"),
        ],
        "measures": [
            _measure("Total Advertisers", "COUNTROWS(dim_advertiser)",
                     "Number of advertisers", fmt=NUM, folder="Counts"),
        ],
        "partitions": [_partition("dim_advertiser")],
    })

    # ── dim_brand ────────────────────────────────────────────────
    tables.append({
        "name": "dim_brand", "lineageTag": _tag(),
        "description": "Brands belonging to an advertiser",
        "columns": [
            _col("brand_id", "string", "Brand code", summarize_none=True),
            _col("brand_name", "string", "Brand display name"),
            _col("advertiser_id", "string", "Advertiser FK", hidden=True, summarize_none=True),
            _col("category", "string", "Product category"),
        ],
        "measures": [
            _measure("Total Brands", "COUNTROWS(dim_brand)",
                     "Number of brands", fmt=NUM, folder="Counts"),
        ],
        "partitions": [_partition("dim_brand")],
    })

    # ── dim_campaign ─────────────────────────────────────────────
    tables.append({
        "name": "dim_campaign", "lineageTag": _tag(),
        "description": "Media campaigns — the unit a plan is booked and delivered against",
        "columns": [
            _col("campaign_id", "string", "Campaign code", summarize_none=True),
            _col("campaign_name", "string", "Campaign display name"),
            _col("advertiser_id", "string", "Advertiser FK", hidden=True, summarize_none=True),
            _col("brand_id", "string", "Brand FK", hidden=True, summarize_none=True),
            _col("market_id", "string", "Market FK", hidden=True, summarize_none=True),
            _col("objective", "string", "Campaign objective (Awareness, Performance, ...)"),
            _col("quarter", "string", "Fiscal quarter (e.g. 2026-Q2)", summarize_none=True),
            _col("start_date", "string", "Flight start date", summarize_none=True),
            _col("end_date", "string", "Flight end date", summarize_none=True),
            _col("status", "string", "Campaign status"),
            _col("planned_budget_eur", "double", "Campaign-level planned budget",
                 fmt=EUR, summarize_none=True),
        ],
        "measures": [
            _measure("Total Campaigns", "COUNTROWS(dim_campaign)",
                     "Number of campaigns", fmt=NUM, folder="Counts"),
            _measure("Active Campaigns",
                     'CALCULATE(COUNTROWS(dim_campaign), dim_campaign[status] = "Live")',
                     "Number of campaigns currently live", fmt=NUM, folder="Counts"),
        ],
        "partitions": [_partition("dim_campaign")],
    })

    # ── dim_market ───────────────────────────────────────────────
    tables.append({
        "name": "dim_market", "lineageTag": _tag(),
        "description": "Markets (countries) the agency buys media in",
        "columns": [
            _col("market_id", "string", "Market code", summarize_none=True),
            _col("market_name", "string", "Market display name"),
            _col("country_code", "string", "ISO country code"),
            _col("currency", "string", "Local currency"),
            _col("region", "string", "Region grouping"),
        ],
        "measures": [
            _measure("Total Markets", "COUNTROWS(dim_market)",
                     "Number of markets", fmt=NUM, folder="Counts"),
        ],
        "partitions": [_partition("dim_market")],
    })

    # ── dim_channel ──────────────────────────────────────────────
    tables.append({
        "name": "dim_channel", "lineageTag": _tag(),
        "description": "Media channels. GRP channels are measured in gross rating points, "
                       "the others in impressions — never sum the two.",
        "columns": [
            _col("channel_id", "string", "Channel code", summarize_none=True),
            _col("channel_name", "string", "Channel display name"),
            _col("channel_group", "string", "Channel group (Offline, Digital, ...)"),
            _col("measurement_unit", "string", "Unit the channel is traded in (Impressions or GRP)"),
            _col("rate_card_cpm_eur", "double", "Rate-card CPM", fmt=EUR, summarize_none=True),
            _col("is_grp_channel", "boolean", "TRUE when the channel is traded in GRP",
                 summarize_none=True),
        ],
        "measures": [
            _measure("Total Channels", "COUNTROWS(dim_channel)",
                     "Number of channels", fmt=NUM, folder="Counts"),
        ],
        "partitions": [_partition("dim_channel")],
    })

    # ── dim_media_owner ──────────────────────────────────────────
    tables.append({
        "name": "dim_media_owner", "lineageTag": _tag(),
        "description": "Media owners the agency buys from. agency_discount_pct and rebate_pct "
                       "are what the OWNER grants the AGENCY — not what the agency owes the "
                       "advertiser. That is a contract term and is not in this model.",
        "columns": [
            _col("media_owner_id", "string", "Media owner code", summarize_none=True),
            _col("media_owner_name", "string", "Media owner display name"),
            _col("owner_type", "string", "Owner type (Broadcaster, Platform, Publisher, ...)"),
            _col("channels_sold", "string", "Channels the owner sells"),
            _col("primary_channel_id", "string", "Primary channel FK", hidden=True,
                 summarize_none=True),
            _col("agency_discount_pct", "double", "Discount granted by the owner to the agency",
                 fmt=PCT, summarize_none=True),
            _col("rebate_pct", "double", "Volume rebate granted by the owner to the agency",
                 fmt=PCT, summarize_none=True),
        ],
        "measures": [
            _measure("Total Media Owners", "COUNTROWS(dim_media_owner)",
                     "Number of media owners", fmt=NUM, folder="Counts"),
        ],
        "partitions": [_partition("dim_media_owner")],
    })

    # ── dim_date ─────────────────────────────────────────────────
    tables.append({
        "name": "dim_date", "lineageTag": _tag(),
        "description": "Calendar. date_key is a STRING (YYYY-MM-DD) so it joins the "
                       "delivery grain exactly, and month is a STRING (YYYY-MM) so it "
                       "joins the monthly plan and billing grain. Declaring month int64 "
                       "made every visual keyed on it fail: the column is '2026-04'.",
        "columns": [
            _col("date_key", "string", "Date key (YYYY-MM-DD)", summarize_none=True),
            _col("year", "int64", "Calendar year", fmt="0", summarize_none=True),
            _col("quarter", "string", "Calendar quarter", summarize_none=True),
            _col("month", "string", "Month key (YYYY-MM)", summarize_none=True),
            _col("month_name", "string", "Month name"),
            _col("day_of_month", "int64", "Day of month", fmt="0", summarize_none=True),
            _col("week_of_year", "int64", "ISO week", fmt="0", summarize_none=True),
            _col("day_of_week", "int64", "Day of week number", fmt="0", summarize_none=True),
            _col("day_name", "string", "Day name"),
            _col("is_weekend", "boolean", "TRUE on Saturday and Sunday", summarize_none=True),
        ],
        "measures": [],
        "partitions": [_partition("dim_date")],
    })

    # ── fact_plan ────────────────────────────────────────────────
    tables.append({
        "name": "fact_plan", "lineageTag": _tag(),
        "description": "The BOOKED plan: what was committed per campaign x channel x owner x "
                       "month. This is the denominator of every delivery ratio.",
        "columns": [
            _col("plan_id", "string", "Plan line code", hidden=True, summarize_none=True),
            _col("campaign_id", "string", "Campaign FK", hidden=True, summarize_none=True),
            _col("channel_id", "string", "Channel FK", hidden=True, summarize_none=True),
            _col("media_owner_id", "string", "Media owner FK", hidden=True, summarize_none=True),
            _col("month", "string", "Plan month (YYYY-MM)", summarize_none=True),
            _col("planned_budget_eur", "double", "Planned budget for the line", fmt=EUR),
            _col("planned_impressions", "int64", "Planned impressions", fmt=NUM),
            _col("planned_grp", "double", "Planned GRP (GRP channels only)", fmt="#,0.0"),
        ],
        "measures": [
            _measure("Planned Budget (EUR)", "SUM(fact_plan[planned_budget_eur])",
                     "Total booked budget", fmt=EUR, folder="Plan"),
            _measure("Planned Impressions", "SUM(fact_plan[planned_impressions])",
                     "Total booked impressions — the denominator of [Delivery vs Plan %]",
                     fmt=NUM, folder="Plan"),
            _measure("Planned GRP", "SUM(fact_plan[planned_grp])",
                     "Total booked GRP (GRP channels only)", fmt="#,0.0", folder="Plan"),
        ],
        "partitions": [_partition("fact_plan")],
    })

    # ── fact_delivery ────────────────────────────────────────────
    tables.append({
        "name": "fact_delivery", "lineageTag": _tag(),
        "description": "What was ACTUALLY delivered, daily, per campaign x channel x owner. "
                       "The numerator of every delivery ratio.",
        "columns": [
            _col("date_key", "string", "Date FK", hidden=True, summarize_none=True),
            _col("campaign_id", "string", "Campaign FK", hidden=True, summarize_none=True),
            _col("channel_id", "string", "Channel FK", hidden=True, summarize_none=True),
            _col("media_owner_id", "string", "Media owner FK", hidden=True, summarize_none=True),
            _col("impressions", "int64", "Impressions delivered", fmt=NUM),
            _col("clicks", "int64", "Clicks", fmt=NUM),
            _col("spend_net_eur", "double", "Net spend", fmt=EUR),
            _col("delivered_grp", "double", "GRP delivered (GRP channels only)", fmt="#,0.0"),
        ],
        "measures": [
            _measure("Delivered Impressions", "SUM(fact_delivery[impressions])",
                     "Total impressions delivered — the numerator of [Delivery vs Plan %]",
                     fmt=NUM, folder="Delivery"),
            _measure("Delivered Clicks", "SUM(fact_delivery[clicks])", "Total clicks",
                     fmt=NUM, folder="Delivery"),
            _measure("Net Spend (EUR)", "SUM(fact_delivery[spend_net_eur])",
                     "Total net spend against delivery", fmt=EUR, folder="Delivery"),
            _measure("Delivered GRP", "SUM(fact_delivery[delivered_grp])",
                     "Total GRP delivered", fmt="#,0.0", folder="Delivery"),
            _measure("CTR %", "DIVIDE([Delivered Clicks], [Delivered Impressions])",
                     "Clicks divided by impressions", fmt=PCT, folder="Delivery"),
            _measure("Effective CPM (EUR)",
                     "DIVIDE([Net Spend (EUR)], [Delivered Impressions]) * 1000",
                     "Net spend per thousand impressions actually delivered",
                     fmt="\\€#,0.00", folder="Delivery"),

            # ── THE demo measure ─────────────────────────────────
            _measure("Delivery vs Plan %",
                     "VAR Planned = [Planned Impressions]\n"
                     "VAR Delivered = [Delivered Impressions]\n"
                     "RETURN IF(Planned > 0, DIVIDE(Delivered, Planned) - 1)",
                     "Over- (positive) or under-delivery (negative) against the booked plan. "
                     "Hand-checkable: delivered impressions / planned impressions - 1.",
                     fmt=PCT, folder="Delivery vs Plan"),
            _measure("Delivery Ratio",
                     "DIVIDE([Delivered Impressions], [Planned Impressions])",
                     "Delivered / planned as a ratio (1.0 = exactly on plan)",
                     fmt="0.00", folder="Delivery vs Plan"),
            _measure("Impression Gap",
                     "[Delivered Impressions] - [Planned Impressions]",
                     "Absolute over/under-delivery in impressions", fmt=NUM,
                     folder="Delivery vs Plan"),
            _measure("GRP Delivery %",
                     "VAR P = [Planned GRP]\n"
                     "RETURN IF(P > 0, DIVIDE([Delivered GRP], P) - 1)",
                     "Over/under-delivery on GRP channels only", fmt=PCT,
                     folder="Delivery vs Plan"),
            _measure("Over-delivered Campaigns",
                     "COUNTROWS(FILTER(VALUES(dim_campaign[campaign_id]), "
                     "[Delivery vs Plan %] > 0.05))",
                     "Campaigns delivering more than 5% above plan", fmt=NUM,
                     folder="Delivery vs Plan"),
            _measure("Under-delivered Campaigns",
                     "COUNTROWS(FILTER(VALUES(dim_campaign[campaign_id]), "
                     "[Delivery vs Plan %] < -0.05))",
                     "Campaigns delivering more than 5% below plan", fmt=NUM,
                     folder="Delivery vs Plan"),
            _measure("Budget Consumption %",
                     "DIVIDE([Net Spend (EUR)], [Planned Budget (EUR)])",
                     "Net spend against booked budget", fmt=PCT, folder="Delivery vs Plan"),
        ],
        "partitions": [_partition("fact_delivery")],
    })

    # ── fact_billing ─────────────────────────────────────────────
    tables.append({
        "name": "fact_billing", "lineageTag": _tag(),
        "description": "Invoices from media owners. gross -> net (agency discount) -> "
                       "net-net (volume rebate). [Rebate % of Gross] is what was ACTUALLY "
                       "rebated; whether it matches the contract is a Foundry question.",
        "columns": [
            _col("invoice_id", "string", "Invoice number", summarize_none=True),
            _col("campaign_id", "string", "Campaign FK", hidden=True, summarize_none=True),
            _col("media_owner_id", "string", "Media owner FK", hidden=True, summarize_none=True),
            _col("month", "string", "Billing month (YYYY-MM)", summarize_none=True),
            _col("gross_amount_eur", "double", "Gross amount before any discount", fmt=EUR),
            _col("net_amount_eur", "double", "Amount after agency discount", fmt=EUR),
            _col("rebate_amount_eur", "double", "Volume rebate amount", fmt=EUR),
            _col("net_net_amount_eur", "double", "Amount after discount and rebate", fmt=EUR),
            _col("invoice_status", "string", "Invoice status (Paid, Open, Disputed)"),
            _col("invoice_date", "string", "Invoice date", summarize_none=True),
        ],
        "measures": [
            _measure("Gross Billed (EUR)", "SUM(fact_billing[gross_amount_eur])",
                     "Gross invoiced amount", fmt=EUR, folder="Billing"),
            _measure("Net Billed (EUR)", "SUM(fact_billing[net_amount_eur])",
                     "Invoiced amount after agency discount", fmt=EUR, folder="Billing"),
            _measure("Rebate Amount (EUR)", "SUM(fact_billing[rebate_amount_eur])",
                     "Volume rebate actually applied", fmt=EUR, folder="Billing"),
            _measure("Net Net Billed (EUR)", "SUM(fact_billing[net_net_amount_eur])",
                     "Final invoiced amount after discount and rebate", fmt=EUR,
                     folder="Billing"),
            _measure("Rebate % of Gross",
                     "DIVIDE([Rebate Amount (EUR)], [Gross Billed (EUR)])",
                     "Rebate actually applied as a share of gross. Compare against the "
                     "contractual rate retrieved by Foundry — this model does not hold it.",
                     fmt=PCT, folder="Billing"),
            _measure("Total Invoices", "COUNTROWS(fact_billing)",
                     "Number of invoices", fmt=NUM, folder="Billing"),
            _measure("Disputed Invoices",
                     'CALCULATE(COUNTROWS(fact_billing), fact_billing[invoice_status] = "Disputed")',
                     "Invoices in dispute", fmt=NUM, folder="Billing"),
            _measure("Disputed Amount (EUR)",
                     'CALCULATE([Gross Billed (EUR)], fact_billing[invoice_status] = "Disputed")',
                     "Gross amount currently in dispute", fmt=EUR, folder="Billing"),
            _measure("Billing vs Spend Gap (EUR)",
                     "[Net Net Billed (EUR)] - [Net Spend (EUR)]",
                     "Difference between what was invoiced and what delivery accounted for",
                     fmt=EUR, folder="Billing"),
        ],
        "partitions": [_partition("fact_billing")],
    })

    # Advertiser -> Brand -> Campaign is the ONLY path to the advertiser.
    # dim_campaign[advertiser_id] is deliberately NOT related: it would create a second
    # path to dim_advertiser and Power BI would deactivate one of them silently.
    relationships = [
        {"name": "rel_brand_advertiser", "fromTable": "dim_brand", "fromColumn": "advertiser_id",
         "toTable": "dim_advertiser", "toColumn": "advertiser_id"},
        {"name": "rel_campaign_brand", "fromTable": "dim_campaign", "fromColumn": "brand_id",
         "toTable": "dim_brand", "toColumn": "brand_id"},
        {"name": "rel_campaign_market", "fromTable": "dim_campaign", "fromColumn": "market_id",
         "toTable": "dim_market", "toColumn": "market_id"},
        {"name": "rel_plan_campaign", "fromTable": "fact_plan", "fromColumn": "campaign_id",
         "toTable": "dim_campaign", "toColumn": "campaign_id"},
        {"name": "rel_plan_channel", "fromTable": "fact_plan", "fromColumn": "channel_id",
         "toTable": "dim_channel", "toColumn": "channel_id"},
        {"name": "rel_plan_owner", "fromTable": "fact_plan", "fromColumn": "media_owner_id",
         "toTable": "dim_media_owner", "toColumn": "media_owner_id"},
        {"name": "rel_delivery_campaign", "fromTable": "fact_delivery", "fromColumn": "campaign_id",
         "toTable": "dim_campaign", "toColumn": "campaign_id"},
        {"name": "rel_delivery_channel", "fromTable": "fact_delivery", "fromColumn": "channel_id",
         "toTable": "dim_channel", "toColumn": "channel_id"},
        {"name": "rel_delivery_owner", "fromTable": "fact_delivery", "fromColumn": "media_owner_id",
         "toTable": "dim_media_owner", "toColumn": "media_owner_id"},
        {"name": "rel_delivery_date", "fromTable": "fact_delivery", "fromColumn": "date_key",
         "toTable": "dim_date", "toColumn": "date_key"},
        {"name": "rel_billing_campaign", "fromTable": "fact_billing", "fromColumn": "campaign_id",
         "toTable": "dim_campaign", "toColumn": "campaign_id"},
        {"name": "rel_billing_owner", "fromTable": "fact_billing", "fromColumn": "media_owner_id",
         "toTable": "dim_media_owner", "toColumn": "media_owner_id"},
    ]

    for t in tables:
        for c in t.get("columns", []):
            if "lineageTag" not in c:
                c["lineageTag"] = _tag()

    rels = [{"name": r["name"], "fromTable": r["fromTable"], "fromColumn": r["fromColumn"],
             "toTable": r["toTable"], "toColumn": r["toColumn"],
             "crossFilteringBehavior": "oneDirection"} for r in relationships]

    lh_id = state.get("lakehouse_id", "")
    lh_name = config.get("lakehouse_name", "ZavaMediaLH")
    sql_endpoint = state.get("lakehouse_sql_endpoint", "")
    if lh_id and not sql_endpoint:
        h_tmp = fabric_headers(get_fabric_token())
        r_lh = requests.get(f"{API_BASE}/workspaces/{state['workspace_id']}/lakehouses/{lh_id}",
                            headers=h_tmp, timeout=60)
        if r_lh.status_code == 200:
            sql_endpoint = (r_lh.json().get("properties", {})
                            .get("sqlEndpointProperties", {}).get("connectionString", ""))

    expressions = [{
        "name": "DatabaseQuery", "kind": "m", "lineageTag": _tag(),
        "expression": ["let",
                       f'    database = Sql.Database("{sql_endpoint}", "{lh_name}")',
                       "in", "    database"],
    }]

    copilot_instructions = (
        "This model analyses a media agency's booked plan, actual delivery and supplier "
        "billing across advertisers, brands, campaigns, markets, channels and media owners. "
        "Always use the existing measures rather than aggregating columns by hand. "
        "Plan: [Planned Budget (EUR)], [Planned Impressions], [Planned GRP]. "
        "Delivery: [Delivered Impressions], [Delivered Clicks], [Net Spend (EUR)], [Delivered GRP], "
        "[CTR %], [Effective CPM (EUR)]. "
        "Plan versus delivery: [Delivery vs Plan %] is the primary answer to any over- or "
        "under-delivery question; supporting measures are [Delivery Ratio], [Impression Gap], "
        "[GRP Delivery %], [Over-delivered Campaigns], [Under-delivered Campaigns], "
        "[Budget Consumption %]. "
        "Billing: [Gross Billed (EUR)], [Net Billed (EUR)], [Rebate Amount (EUR)], "
        "[Net Net Billed (EUR)], [Rebate % of Gross], [Total Invoices], [Disputed Invoices], "
        "[Disputed Amount (EUR)]. "
        "GRP and impressions are different units — never add them together, and only use GRP "
        "measures when dim_channel[is_grp_channel] is TRUE. "
        "For advertisers, brands, markets, channels and media owners use "
        "dim_advertiser[advertiser_name], dim_brand[brand_name], dim_market[market_name], "
        "dim_channel[channel_name], dim_media_owner[media_owner_name]. "
        "The advertiser is reached through the brand, not directly from the campaign. "
        "For rankings use TOPN over the existing measures. "
        "This model contains NO contractual terms. Questions about what a contract entitles "
        "an advertiser to, about rebate pass-through obligations or about audit rights cannot "
        "be answered here — say so and state the measured figure instead."
    )

    model_bim = {
        "compatibilityLevel": 1604,
        "model": {
            "defaultPowerBIDataSourceVersion": "PowerBI_V3",
            "defaultMode": "directLake",
            "discourageImplicitMeasures": True,
            "tables": tables,
            "relationships": rels,
            "expressions": expressions,
            "culture": "en-US",
            "annotations": [
                {"name": "__PBI_CopilotInstructions", "value": copilot_instructions},
                {"name": "__PBI_LinguisticSchema", "value": json.dumps({
                    "Version": "1.0.0", "Language": "en-US",
                    "DynamicImprovement": "HighConfidence",
                    "Entities": {
                        "dim_advertiser": {"Definition": {"Binding": {"ConceptualEntity": "dim_advertiser"}},
                                           "State": "Generated",
                                           "Terms": [["advertiser"], ["client"], ["account"]]},
                        "dim_brand": {"Definition": {"Binding": {"ConceptualEntity": "dim_brand"}},
                                      "State": "Generated", "Terms": [["brand"], ["product"]]},
                        "dim_campaign": {"Definition": {"Binding": {"ConceptualEntity": "dim_campaign"}},
                                         "State": "Generated",
                                         "Terms": [["campaign"], ["flight"], ["burst"]]},
                        "dim_market": {"Definition": {"Binding": {"ConceptualEntity": "dim_market"}},
                                       "State": "Generated", "Terms": [["market"], ["country"]]},
                        "dim_channel": {"Definition": {"Binding": {"ConceptualEntity": "dim_channel"}},
                                        "State": "Generated",
                                        "Terms": [["channel"], ["medium"], ["media type"]]},
                        "dim_media_owner": {"Definition": {"Binding": {"ConceptualEntity": "dim_media_owner"}},
                                            "State": "Generated",
                                            "Terms": [["media owner"], ["supplier"], ["publisher"], ["broadcaster"]]},
                        "dim_date": {"Definition": {"Binding": {"ConceptualEntity": "dim_date"}},
                                     "State": "Generated", "Terms": [["date"], ["calendar"], ["day"]]},
                        "fact_plan": {"Definition": {"Binding": {"ConceptualEntity": "fact_plan"}},
                                      "State": "Generated",
                                      "Terms": [["plan"], ["booking"], ["planned"]]},
                        "fact_delivery": {"Definition": {"Binding": {"ConceptualEntity": "fact_delivery"}},
                                          "State": "Generated",
                                          "Terms": [["delivery"], ["delivered"], ["actual"]]},
                        "fact_billing": {"Definition": {"Binding": {"ConceptualEntity": "fact_billing"}},
                                         "State": "Generated",
                                         "Terms": [["billing"], ["invoice"], ["rebate"]]},
                    },
                })},
                {"name": "PBI_ProTooling", "value": json.dumps(
                    ["DirectLakeOnOneLakeInWeb", "WebModelingEdit", "DaxQueryView_Desktop",
                     "CopilotTooling", "MCP-PBIModeling"])},
                {"name": "__PBI_TimeIntelligenceEnabled", "value": "1"},
                {"name": "PBI_QueryOrder", "value": json.dumps([f"DirectLake - {lh_name}"])},
                {"name": "__PBI_VerifiedAnswers", "value": json.dumps([
                    {"Question": "Which advertiser over-delivered the most?",
                     "Answer": {"Query": 'EVALUATE TOPN(1, ADDCOLUMNS(VALUES(dim_advertiser[advertiser_name]), "Gap", [Delivery vs Plan %]), [Gap], DESC)',
                                "Description": "Advertiser with the highest over-delivery against plan"}},
                    {"Question": "What is the over-delivery by advertiser and market?",
                     "Answer": {"Query": 'EVALUATE SUMMARIZECOLUMNS(dim_advertiser[advertiser_name], dim_market[market_name], "Planned", [Planned Impressions], "Delivered", [Delivered Impressions], "Delivery vs Plan", [Delivery vs Plan %])',
                                "Description": "Planned vs delivered impressions per advertiser and market"}},
                    {"Question": "How many campaigns over-delivered?",
                     "Answer": {"Query": 'EVALUATE ROW("Over", [Over-delivered Campaigns])',
                                "Description": "Campaigns delivering more than 5% above plan"}},
                    {"Question": "What rebate was actually applied?",
                     "Answer": {"Query": 'EVALUATE ROW("Rebate", [Rebate Amount (EUR)], "Rebate pct", [Rebate % of Gross])',
                                "Description": "Rebate amount and its share of gross billing"}},
                    {"Question": "Which media owner has the largest disputed amount?",
                     "Answer": {"Query": 'EVALUATE TOPN(1, ADDCOLUMNS(VALUES(dim_media_owner[media_owner_name]), "Disputed", [Disputed Amount (EUR)]), [Disputed], DESC)',
                                "Description": "Media owner with the highest disputed gross amount"}},
                    {"Question": "What is the effective CPM by channel?",
                     "Answer": {"Query": 'EVALUATE SUMMARIZECOLUMNS(dim_channel[channel_name], "eCPM", [Effective CPM (EUR)])',
                                "Description": "Net spend per thousand delivered impressions per channel"}},
                ])},
            ],
        },
    }
    return model_bim


def main():
    config = load_config(); state = load_state()
    global API_BASE
    API_BASE = config["fabric_api_base"]
    ws_id = state.get("workspace_id")
    if not ws_id:
        print("Workspace not created. Run deploy_workspace.py first."); sys.exit(1)

    token = get_fabric_token(); headers = fabric_headers(token)
    sm_name = config.get("semantic_model_name", "SM_Zava_Media")

    print_step(1, 2, f"Build model.bim for '{sm_name}'")
    model_bim = build_model_bim(config, state)
    tcount = len(model_bim["model"]["tables"])
    mcount = sum(len(t.get("measures", [])) for t in model_bim["model"]["tables"])
    rcount = len(model_bim["model"]["relationships"])
    print(f"   {tcount} tables, {mcount} measures, {rcount} relationships")

    definition = {"parts": [
        {"path": "definition.pbism", "payload": b64encode_json({"version": "1.0"}),
         "payloadType": "InlineBase64"},
        {"path": "model.bim", "payload": b64encode_json(model_bim), "payloadType": "InlineBase64"},
    ]}

    print_step(2, 2, "Create or update the semantic model")
    sm_id = state.get("semantic_model_id")
    if not sm_id:
        try:
            sm_id = find_item(token, API_BASE, ws_id, sm_name, "SemanticModel")["id"]
        except RuntimeError:
            sm_id = None

    if sm_id:
        print(f"   updating {sm_id}")
        resp = requests.post(
            f"{API_BASE}/workspaces/{ws_id}/semanticModels/{sm_id}/updateDefinition",
            headers=headers, json={"definition": definition}, timeout=180)
    else:
        print("   creating new model...")
        resp = requests.post(
            f"{API_BASE}/workspaces/{ws_id}/items", headers=headers,
            json={"displayName": sm_name, "type": "SemanticModel",
                  "description": "Zava Media — plan vs delivery vs billing (Direct Lake)",
                  "definition": definition}, timeout=180)

    if resp.status_code in (200, 201):
        sm_id = resp.json().get("id", sm_id)
    elif resp.status_code == 202:
        op_id = resp.headers.get("x-ms-operation-id", "")
        if op_id:
            print(f"   polling operation {op_id}...")
            poll_operation(token, API_BASE, op_id)
        if not sm_id:
            sm_id = find_item(token, API_BASE, ws_id, sm_name, "SemanticModel")["id"]
    else:
        raise RuntimeError(f"Semantic model deploy failed ({resp.status_code}): {resp.text[:600]}")

    state["semantic_model_id"] = sm_id
    save_state(state)
    print(f"   semantic_model_id = {sm_id}")
    print("\nOK. Next: deploy_data_agent.py")


if __name__ == "__main__":
    main()
