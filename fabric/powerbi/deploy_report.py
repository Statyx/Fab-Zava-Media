#!/usr/bin/env python3
"""
Deploy Power BI report Zava_Media_Report — PBIR folder format, over SM_Zava_Media.

WHY THIS REPORT EXISTS. The demo's claim is that one answer needs two halves: a
number Fabric can compute and a clause only Foundry can retrieve. Page 3 makes
that visible on a canvas — it shows what WAS rebated and states, in a textbox,
that what SHOULD have been rebated lives in the contract. A demo that only shows
an agent chat leaves the audience unable to check the number; this report is the
audit trail behind it.

FORMAT IS NOT NEGOTIABLE — see report-builder-agent/known_issues.md #19. A report
that validates 0/0 can still hang forever on "Loading your report...". The four
conditions, all enforced below:

  * version.json          "2.0.0"      (NOT "4.0.0")
  * report.json           must carry reportSource + settings + objects
  * baseTheme             a REAL built-in name (CY26SU05) with its theme json
  * visualContainer       the NEWEST EXISTING schema — measured, not assumed

⚠️ On that last point the brain is wrong and this file is right. known_issues #19
says "visualContainer schema 2.10.0 (not 2.5.0)". Measured 2026-09-02 with curl
against the schema host: 2.10.0 → 404, and so do 2.11.0 through 2.14.0. 2.9.0 →
200, and it is the version report.json itself declares in reportVersionAtImport.
Pinning a 404 schema is not a harmless typo: the CLI reports PBIR_SCHEMA_UNREACHABLE
as a *warning*, silently skips validation for every visual, and still prints
"failed: 0 errors" if nothing else is wrong — so the visuals ship unchecked.
Use 2.9.0. Re-measure before bumping.

Every formatting value is a PBIR literal expression: strings single-quote padded,
doubles suffixed D, integers suffixed L, colors wrapped in solid.color.

Run:  python -m fabric.powerbi.deploy_report
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import json, base64
from pathlib import Path
import requests

from fabric._shared.helpers import (load_config, load_state, save_state,
                     get_fabric_token, fabric_headers,
                     poll_operation, find_item, print_step)
from fabric._shared.paths import POWERBI, ROOT

API_BASE = None

# ── Schema URLs. Every one of these returns 200 from the schema host — verified
# with curl, because a 404 here degrades to a skipped validation, not an error.
S = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
SCHEMA_VISUAL = f"{S}/visualContainer/2.9.0/schema.json"   # 2.10.0+ are 404
SCHEMA_PAGE = f"{S}/page/2.1.0/schema.json"                # 2.3.1 is 404
SCHEMA_PAGES = f"{S}/pagesMetadata/1.1.0/schema.json"
SCHEMA_REPORT = f"{S}/report/3.3.0/schema.json"
SCHEMA_VERSION = f"{S}/versionMetadata/1.0.0/schema.json"
SCHEMA_PBIR = ("https://developer.microsoft.com/json-schemas/fabric/item/report/"
               "definitionProperties/2.0.0/schema.json")

THEME_NAME = "CY26SU05"
CANVAS_W, CANVAS_H = 1280, 720

# ── Brand palette. Zava Media reads as a media agency, not a Power BI sample.
INK = "'#1B1F3B'"        # headers
CARD_BG = "'#FFFFFF'"
PAGE_BG = "'#F3F4F8'"
ACCENT = "'#118DFF'"
WARN = "'#E66C37'"       # over-delivery / dispute
GOOD = "'#1AAB40'"


# ── PBIR literal encoders (Rule 3) ────────────────────────────────────────
def s(v):
    """String literal — note the single-quote padding inside the JSON string."""
    return {"expr": {"Literal": {"Value": f"'{v}'"}}}


def d(v):
    return {"expr": {"Literal": {"Value": f"{v}D"}}}


def i(v):
    return {"expr": {"Literal": {"Value": f"{v}L"}}}


def b(v):
    return {"expr": {"Literal": {"Value": "true" if v else "false"}}}


def color(hex_padded):
    """hex_padded already carries its single quotes, e.g. ACCENT."""
    return {"solid": {"color": {"expr": {"Literal": {"Value": hex_padded}}}}}


def measure(entity, name):
    return {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": entity}},
                                  "Property": name}},
            "queryRef": f"{entity}.{name}", "nativeQueryRef": name}


def column(entity, name):
    return {"field": {"Column": {"Expression": {"SourceRef": {"Entity": entity}},
                                 "Property": name}},
            "queryRef": f"{entity}.{name}", "nativeQueryRef": name}


def title_vco(text, size=11):
    return [{"properties": {"show": b(True), "text": s(text),
                            "fontSize": d(size), "bold": b(True),
                            "fontColor": color(INK)}}]


def card_chrome(text):
    """Container styling shared by every card. Title, white plate, soft shadow."""
    return {
        "title": title_vco(text, 10),
        "background": [{"properties": {"show": b(True), "color": color(CARD_BG),
                                       "transparency": i(0)}}],
        "dropShadow": [{"properties": {
            "show": b(True), "color": color("'#000000'"), "transparency": i(92),
            "shadowBlur": i(8), "preset": s("BottomRight"), "position": s("Outer")}}],
        "border": [{"properties": {"show": b(False)}}],
    }


def chart_chrome(text):
    return {
        "title": title_vco(text),
        "background": [{"properties": {"show": b(True), "color": color(CARD_BG)}}],
        "padding": [{"properties": {"left": d(8), "right": d(8),
                                    "top": d(8), "bottom": d(8)}}],
        "dropShadow": [{"properties": {
            "show": b(True), "color": color("'#000000'"), "transparency": i(92),
            "shadowBlur": i(8), "preset": s("BottomRight"), "position": s("Outer")}}],
        "border": [{"properties": {"show": b(False)}}],
    }


# ── Visual builders ───────────────────────────────────────────────────────
def card(name, x, y, w, title, entity, measure_name, value_color=INK, h=120):
    """
    Height is never below 120 and value.fontSize is always explicit —
    known_issues #16: a shorter card clips the callout, and cardCalloutArea
    has no fontSize property (it owns padding/background/cornerRadius only).
    """
    return {
        "$schema": SCHEMA_VISUAL, "name": name,
        "position": {"x": x, "y": y, "z": 1500, "width": w, "height": h, "tabOrder": 0},
        "visual": {
            "visualType": "cardVisual",
            "query": {"queryState": {"Data": {"projections": [measure(entity, measure_name)]}},
                      "sortDefinition": {"sort": [], "isDefaultSort": True}},
            "objects": {"value": [{"properties": {"fontSize": d(26), "bold": b(True),
                                                  "fontColor": color(value_color)}}]},
            "visualContainerObjects": card_chrome(title),
            "drillFilterOtherVisuals": True,
        },
    }


def bar(name, x, y, w, h, title, cat_entity, cat_col, val_entity, val_measure,
        visual_type="barChart", extra_measures=None, legend=False):
    y_projections = [measure(val_entity, val_measure)]
    for ent, m in (extra_measures or []):
        y_projections.append(measure(ent, m))
    return {
        "$schema": SCHEMA_VISUAL, "name": name,
        "position": {"x": x, "y": y, "z": 1000, "width": w, "height": h, "tabOrder": 0},
        "visual": {
            "visualType": visual_type,
            "query": {
                "queryState": {
                    "Category": {"projections": [column(cat_entity, cat_col)]},
                    "Y": {"projections": y_projections},
                },
                "sortDefinition": {
                    "sort": [{"field": {"Measure": {
                        "Expression": {"SourceRef": {"Entity": val_entity}},
                        "Property": val_measure}}, "direction": "Descending"}],
                    "isDefaultSort": False},
            },
            "objects": {
                "legend": [{"properties": {"show": b(legend), "position": s("Top")}}],
                "labels": [{"properties": {"show": b(False)}}],
            },
            "visualContainerObjects": chart_chrome(title),
            "drillFilterOtherVisuals": True,
        },
    }


def line(name, x, y, w, h, title, series):
    """series: list of (entity, measure_name), plotted over dim_date[month_name]."""
    return {
        "$schema": SCHEMA_VISUAL, "name": name,
        "position": {"x": x, "y": y, "z": 1000, "width": w, "height": h, "tabOrder": 0},
        "visual": {
            "visualType": "lineChart",
            "query": {
                "queryState": {
                    "Category": {"projections": [column("dim_date", "month")]},
                    "Y": {"projections": [measure(e, m) for e, m in series]},
                },
                "sortDefinition": {
                    "sort": [{"field": {"Column": {
                        "Expression": {"SourceRef": {"Entity": "dim_date"}},
                        "Property": "month"}}, "direction": "Ascending"}],
                    "isDefaultSort": False},
            },
            "objects": {
                "legend": [{"properties": {"show": b(len(series) > 1), "position": s("Top")}}],
                "labels": [{"properties": {"show": b(False)}}],
            },
            "visualContainerObjects": chart_chrome(title),
            "drillFilterOtherVisuals": True,
        },
    }


def table(name, x, y, w, h, title, cols, measures):
    projections = [column(e, c) for e, c in cols] + [measure(e, m) for e, m in measures]
    return {
        "$schema": SCHEMA_VISUAL, "name": name,
        "position": {"x": x, "y": y, "z": 1000, "width": w, "height": h, "tabOrder": 0},
        "visual": {
            "visualType": "tableEx",
            "query": {"queryState": {"Values": {"projections": projections}},
                      "sortDefinition": {"sort": [], "isDefaultSort": True}},
            "objects": {"grid": [{"properties": {"gridVertical": b(True)}}]},
            "visualContainerObjects": chart_chrome(title),
            "drillFilterOtherVisuals": True,
        },
    }


def slicer(name, x, y, w, h, entity, col, title):
    return {
        "$schema": SCHEMA_VISUAL, "name": name,
        "position": {"x": x, "y": y, "z": 2000, "width": w, "height": h, "tabOrder": 0},
        "visual": {
            "visualType": "slicer",
            "query": {"queryState": {"Values": {"projections": [column(entity, col)]}},
                      "sortDefinition": {"sort": [], "isDefaultSort": True}},
            "objects": {"data": [{"properties": {"mode": s("Dropdown")}}]},
            "visualContainerObjects": {
                "title": title_vco(title, 10),
                "background": [{"properties": {"show": b(True), "color": color(CARD_BG)}}],
                "border": [{"properties": {"show": b(False)}}],
            },
            "drillFilterOtherVisuals": True,
        },
    }


def textbox(name, x, y, w, h, runs, bg=None):
    """
    No query — known_issues #9: a non-data visual carrying a query is a defect.
    `runs` is a list of (text, bold, size, color_hex_padded).
    """
    paragraphs = []
    for text, bold, size, col in runs:
        paragraphs.append({"textRuns": [{
            "value": text,
            "textStyle": {"fontSize": f"{size}pt", "fontWeight": "bold" if bold else "normal",
                          "color": col.strip("'")},
        }]})
    vco = {"border": [{"properties": {"show": b(False)}}]}
    if bg:
        vco["background"] = [{"properties": {"show": b(True), "color": color(bg),
                                             "transparency": i(0)}}]
    return {
        "$schema": SCHEMA_VISUAL, "name": name,
        "position": {"x": x, "y": y, "z": 500, "width": w, "height": h, "tabOrder": 0},
        "visual": {
            "visualType": "textbox",
            "objects": {"general": [{"properties": {"paragraphs": paragraphs}}]},
            "visualContainerObjects": vco,
        },
    }


def page(page_id, display_name, ordinal):
    """`ordinal` is NOT a page.json property — schema 2.1.0 rejects it as an
    additional property. Tab order comes from pages.json.pageOrder alone; the
    parameter is kept only to make the caller's intent explicit."""
    return {"$schema": SCHEMA_PAGE, "name": page_id, "displayName": display_name,
            "displayOption": "FitToPage", "height": CANVAS_H, "width": CANVAS_W,
            "visualInteractions": [],
            "objects": {"background": [{"properties": {
                "color": color(PAGE_BG), "transparency": i(0)}}]}}


def header(page_key, title, subtitle):
    return textbox(f"hdr_{page_key}", 24, 16, 1232, 56,
                   [(title, True, 18, INK), ("   " + subtitle, False, 10, "'#5A6070'")])


# ── The three pages ───────────────────────────────────────────────────────
def build_pages():
    """
    Layout grid: 24 px outer margin, 16 px gutter, 1232 px usable width.
    Every visual satisfies x+width <= 1280 and y+height <= 720 (known_issues #11).
    """
    pages = {}

    # ── Page 1 — Delivery Overview ────────────────────────────────────────
    v1 = [
        header("ov", "Zava Media — Delivery Overview",
               "Planned vs delivered across every advertiser, channel and market."),
        card("card_planned_imp", 24, 88, 236, "Planned impressions",
             "fact_plan", "Planned Impressions"),
        card("card_delivered_imp", 272, 88, 236, "Delivered impressions",
             "fact_delivery", "Delivered Impressions"),
        card("card_delivery_vs_plan", 520, 88, 236, "Delivery vs plan",
             "fact_delivery", "Delivery vs Plan %", value_color=WARN),
        card("card_net_spend", 768, 88, 236, "Net spend",
             "fact_delivery", "Net Spend (EUR)"),
        card("card_active_campaigns", 1016, 88, 240, "Active campaigns",
             "dim_campaign", "Active Campaigns"),
        bar("bar_delivery_by_advertiser", 24, 228, 608, 268,
            "Delivery vs plan % by advertiser",
            "dim_advertiser", "advertiser_name", "fact_delivery", "Delivery vs Plan %"),
        line("line_delivery_trend", 648, 228, 608, 268,
             "Planned vs delivered impressions by month",
             [("fact_plan", "Planned Impressions"),
              ("fact_delivery", "Delivered Impressions")]),
        table("tbl_campaign_delivery", 24, 512, 1232, 184,
              "Campaign detail — plan, delivery and spend",
              [("dim_campaign", "campaign_name"), ("dim_market", "market_name")],
              [("fact_plan", "Planned Impressions"),
               ("fact_delivery", "Delivered Impressions"),
               ("fact_delivery", "Delivery vs Plan %"),
               ("fact_delivery", "Net Spend (EUR)")]),
    ]
    pages["delivery_overview"] = (page("delivery_overview", "Delivery Overview", 0), v1)

    # ── Page 2 — Plan vs Delivery ─────────────────────────────────────────
    v2 = [
        header("pvd", "Plan vs Delivery",
               "Where the booked plan and the measured delivery diverge — by channel and owner."),
        slicer("slc_market", 24, 88, 236, 120, "dim_market", "market_name", "Market"),
        card("card_over", 272, 88, 236, "Over-delivered campaigns",
             "fact_delivery", "Over-delivered Campaigns", value_color=WARN),
        card("card_under", 520, 88, 236, "Under-delivered campaigns",
             "fact_delivery", "Under-delivered Campaigns"),
        card("card_gap", 768, 88, 236, "Impression gap",
             "fact_delivery", "Impression Gap", value_color=WARN),
        card("card_grp", 1016, 88, 240, "GRP delivery",
             "fact_delivery", "GRP Delivery %"),
        bar("bar_plan_vs_delivery_channel", 24, 228, 608, 268,
            "Planned vs delivered impressions by channel",
            "dim_channel", "channel_name", "fact_plan", "Planned Impressions",
            visual_type="clusteredColumnChart",
            extra_measures=[("fact_delivery", "Delivered Impressions")], legend=True),
        bar("bar_ratio_by_owner", 648, 228, 608, 268,
            "Delivery ratio by media owner",
            "dim_media_owner", "media_owner_name", "fact_delivery", "Delivery Ratio"),
        table("tbl_channel_detail", 24, 512, 1232, 184,
              "Channel detail — never sum impressions and GRP",
              [("dim_channel", "channel_name"), ("dim_channel", "measurement_unit")],
              [("fact_plan", "Planned Impressions"),
               ("fact_delivery", "Delivered Impressions"),
               ("fact_plan", "Planned GRP"),
               ("fact_delivery", "Delivered GRP"),
               ("fact_delivery", "Effective CPM (EUR)")]),
    ]
    pages["plan_vs_delivery"] = (page("plan_vs_delivery", "Plan vs Delivery", 1), v2)

    # ── Page 3 — Billing & Rebates (the page the demo pivots on) ──────────
    v3 = [
        header("bil", "Billing & Rebates",
               "What was actually rebated. What SHOULD have been is in the contract — ask the agent."),
        card("card_gross", 24, 88, 236, "Gross billed",
             "fact_billing", "Gross Billed (EUR)"),
        card("card_netnet", 272, 88, 236, "Net net billed",
             "fact_billing", "Net Net Billed (EUR)"),
        card("card_rebate", 520, 88, 236, "Rebate amount",
             "fact_billing", "Rebate Amount (EUR)", value_color=GOOD),
        card("card_rebate_pct", 768, 88, 236, "Rebate % of gross",
             "fact_billing", "Rebate % of Gross", value_color=GOOD),
        card("card_disputed", 1016, 88, 240, "Disputed amount",
             "fact_billing", "Disputed Amount (EUR)", value_color=WARN),
        bar("bar_rebate_by_owner", 24, 228, 608, 268,
            "Rebate % of gross by media owner",
            "dim_media_owner", "media_owner_name", "fact_billing", "Rebate % of Gross"),
        textbox("txt_demo_claim", 648, 228, 608, 268,
                [("The number is here. The clause is not.", True, 15, INK),
                 ("", False, 8, INK),
                 ("This page states what Zava Media ACTUALLY rebated, computed in "
                  "Fabric from fact_billing. What each advertiser was CONTRACTUALLY "
                  "owed lives in a signed PDF that no measure can read.", False, 10,
                  "'#3A4055'"),
                 ("", False, 8, INK),
                 ("Zava-Media-Agent crosses the two: it asks Zava_Media_Analyst for "
                  "the figure above, retrieves the matching clause from the contract "
                  "store, and reports the gap. Neither half answers alone.", False, 10,
                  "'#3A4055'"),
                 ("", False, 8, INK),
                 ('Try: "Did we over-deliver for Contoso in Q3, and what does their '
                  'contract say we owe them for it?"', True, 10, ACCENT)],
                bg=CARD_BG),
        table("tbl_billing_detail", 24, 512, 1232, 184,
              "Billing detail by advertiser and media owner",
              [("dim_advertiser", "advertiser_name"),
               ("dim_media_owner", "media_owner_name")],
              [("fact_billing", "Gross Billed (EUR)"),
               ("fact_billing", "Rebate Amount (EUR)"),
               ("fact_billing", "Rebate % of Gross"),
               ("fact_billing", "Disputed Invoices"),
               ("fact_billing", "Billing vs Spend Gap (EUR)")]),
    ]
    pages["billing_rebates"] = (page("billing_rebates", "Billing & Rebates", 2), v3)

    return pages


# ── Folder writer ─────────────────────────────────────────────────────────
def theme_json() -> dict:
    """
    The base theme must be a real built-in name AND ship its json (known_issues
    #19). Only dataColors and the neutral ramp matter for rendering; the rest of
    the built-in file is styling defaults the service fills in.
    """
    return {
        "name": THEME_NAME,
        "dataColors": ["#118DFF", "#12239E", "#E66C37", "#6B007B", "#E044A7",
                       "#744EC2", "#D9B300", "#D64550", "#197278", "#1AAB40",
                       "#15C6F4", "#4092FF", "#FFA058", "#BE5DC9", "#F472D0",
                       "#B5A1FF", "#C4A200", "#FF8080", "#00DBBC", "#5BD667"],
        "foreground": "#1B1F3B",
        "foregroundNeutralSecondary": "#5A6070",
        "foregroundNeutralTertiary": "#8A90A2",
        "background": "#FFFFFF",
        "backgroundLight": "#F3F4F8",
        "backgroundNeutral": "#E4E6EF",
        "tableAccent": "#118DFF",
        "good": "#1AAB40",
        "neutral": "#D9B300",
        "bad": "#D64550",
        "maximum": "#118DFF",
        "center": "#D9B300",
        "minimum": "#E66C37",
        "textClasses": {
            "title": {"fontSize": 14, "fontFace": "Segoe UI Semibold", "color": "#1B1F3B"},
            "label": {"fontSize": 10, "fontFace": "Segoe UI", "color": "#3A4055"},
            "callout": {"fontSize": 26, "fontFace": "Segoe UI Semibold", "color": "#1B1F3B"},
        },
    }


def report_json() -> dict:
    """reportSource + settings + objects are all REQUIRED — known_issues #19."""
    return {
        "$schema": SCHEMA_REPORT,
        "themeCollection": {"baseTheme": {
            "name": THEME_NAME,
            "reportVersionAtImport": {"visual": "2.9.0", "report": "3.3.0", "page": "2.3.1"},
            "type": "SharedResources"}},
        "objects": {
            "section": [{"properties": {"verticalAlignment": s("Top")}}],
            "outspacePane": [{"properties": {"expanded": b(False)}}],
        },
        "reportSource": "QuickCreate",
        "resourcePackages": [{
            "name": "SharedResources", "type": "SharedResources",
            "items": [{"name": THEME_NAME,
                       "path": f"BaseThemes/{THEME_NAME}.json", "type": "BaseTheme"}]}],
        "settings": {
            "useStylableVisualContainerHeader": True,
            "exportDataMode": "AllowSummarized",
            "defaultDrillFilterOtherVisuals": True,
            "allowChangeFilterTypes": True,
            "allowInlineExploration": True,
            "useEnhancedTooltips": True,
            "useDefaultAggregateDisplayName": True,
        },
        "publicCustomVisuals": [],
    }


def connection_string(workspace_name: str, model_name: str, model_id: str) -> str:
    return (f'Data Source="powerbi://api.powerbi.com/v1.0/myorg/{workspace_name}";'
            f"initial catalog={model_name};integrated security=ClaimsToken;"
            f"semanticmodelid={model_id}")


def write_pbir(root: Path, workspace_name: str, model_name: str, model_id: str) -> int:
    """Write the whole PBIR folder. Idempotent: the tree is rebuilt from scratch."""
    import shutil
    if root.exists():
        shutil.rmtree(root)

    defn = root / "definition"
    (defn / "pages").mkdir(parents=True, exist_ok=True)

    def dump(path: Path, obj):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

    dump(root / "definition.pbir", {
        "$schema": SCHEMA_PBIR, "version": "4.0",
        "datasetReference": {"byConnection": {
            "connectionString": connection_string(workspace_name, model_name, model_id)}}})
    dump(defn / "report.json", report_json())
    dump(defn / "version.json", {"$schema": SCHEMA_VERSION, "version": "2.0.0"})
    dump(root / "StaticResources" / "SharedResources" / "BaseThemes" / f"{THEME_NAME}.json",
         theme_json())

    pages = build_pages()
    order = ["delivery_overview", "plan_vs_delivery", "billing_rebates"]
    n_visuals = 0
    for pid in order:
        page_obj, visuals = pages[pid]
        dump(defn / "pages" / pid / "page.json", page_obj)
        for v in visuals:
            dump(defn / "pages" / pid / "visuals" / v["name"] / "visual.json", v)
            n_visuals += 1
    dump(defn / "pages" / "pages.json",
         {"$schema": SCHEMA_PAGES, "activePageName": order[0], "pageOrder": order})
    return n_visuals


def collect_parts(root: Path) -> list:
    """
    updateDefinition is a FULL REPLACE (known_issues #7) — every file in the
    folder must be in parts[], or it is deleted from the report.
    """
    parts = []
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(root).as_posix()
        payload = base64.b64encode(f.read_bytes()).decode("ascii")
        parts.append({"path": rel, "payload": payload, "payloadType": "InlineBase64"})
    return parts


def check_bounds(root: Path) -> list:
    """
    Local guard for known_issues #11 so a bad layout fails before the upload
    rather than rendering off-canvas.
    """
    problems = []
    for f in root.rglob("visual.json"):
        v = json.loads(f.read_text(encoding="utf-8"))
        p = v.get("position", {})
        right, bottom = p.get("x", 0) + p.get("width", 0), p.get("y", 0) + p.get("height", 0)
        if right > CANVAS_W or bottom > CANVAS_H:
            problems.append(f"{v.get('name')}: right={right} bottom={bottom}")
    return problems


def main():
    global API_BASE
    config = load_config()
    state = load_state()
    API_BASE = config["fabric_api_base"]
    ws_id = state["workspace_id"]
    ws_name = config.get("workspace_name", "Zava Media")
    model_name = config.get("semantic_model_name", "SM_Zava_Media")
    report_name = config.get("report_name", "Zava_Media_Report")

    model_id = state.get("semantic_model_id")
    if not model_id:
        raise RuntimeError("semantic_model_id missing from state — run deploy_semantic_model.py first")

    token = get_fabric_token()
    headers = fabric_headers(token)
    root = POWERBI / f"{report_name}.Report"

    print_step(1, 3, f"Build the PBIR folder for '{report_name}'")
    n_visuals = write_pbir(root, ws_name, model_name, model_id)
    print(f"   3 pages, {n_visuals} visuals -> {root.relative_to(ROOT)}")

    print_step(2, 3, "Check layout bounds before uploading")
    problems = check_bounds(root)
    if problems:
        for p in problems:
            print(f"   OFF-CANVAS  {p}")
        raise RuntimeError(f"{len(problems)} visual(s) outside {CANVAS_W}x{CANVAS_H}")
    print(f"   all {n_visuals} visuals inside {CANVAS_W}x{CANVAS_H}")

    print_step(3, 3, "Create or update the report")
    parts = collect_parts(root)
    print(f"   {len(parts)} parts")

    report_id = state.get("report_id")
    if not report_id:
        try:
            report_id = find_item(token, API_BASE, ws_id, report_name, "Report")["id"]
        except RuntimeError:
            report_id = None

    if report_id:
        print(f"   updating {report_id}")
        resp = requests.post(
            f"{API_BASE}/workspaces/{ws_id}/reports/{report_id}/updateDefinition",
            headers=headers, json={"definition": {"parts": parts}}, timeout=300)
    else:
        print("   creating new report...")
        resp = requests.post(
            f"{API_BASE}/workspaces/{ws_id}/reports", headers=headers,
            json={"displayName": report_name,
                  "description": "Zava Media — delivery, plan variance and rebates. "
                                 "Page 3 is the Fabric half of the contract question.",
                  "definition": {"parts": parts}}, timeout=300)

    if resp.status_code in (200, 201):
        report_id = resp.json().get("id", report_id)
    elif resp.status_code == 202:
        op_id = resp.headers.get("x-ms-operation-id", "")
        if op_id:
            print(f"   polling operation {op_id}...")
            poll_operation(token, API_BASE, op_id)
        if not report_id:
            report_id = find_item(token, API_BASE, ws_id, report_name, "Report")["id"]
    else:
        raise RuntimeError(f"Report deploy failed ({resp.status_code}): {resp.text[:600]}")

    state["report_id"] = report_id
    save_state(state)
    print(f"   report_id = {report_id}")
    print(f"\nOK. Open it: https://app.powerbi.com/groups/{ws_id}/reports/{report_id}")


if __name__ == "__main__":
    main()
