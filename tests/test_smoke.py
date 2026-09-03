"""Smoke tests for Zava Media — offline gate (no Fabric tenant needed).

Validates that the committed demo dataset still tells the story the demo depends on:
three delivery gaps whose *numbers* are near-identical but whose *contractual*
consequences are opposite, plus a delivered-never-invoiced anti-join.

If any of these fail, the demo is broken even though nothing looks wrong.

Run BEFORE any deploy:  python -m pytest tests/ -v --tb=short
"""
import ast
import pathlib
import sys

import pandas as pd
import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "artifacts" / "lakehouse_data"
CONTRACTS = ROOT / "design" / "contracts"
sys.path.insert(0, str(ROOT))

# Every hand-written module, wherever its workload folder is. __init__.py carries no logic.
PY_FILES = sorted(
    p for tree in (ROOT / "fabric", ROOT / "foundry", ROOT / "design")
    for p in tree.rglob("*.py") if p.name != "__init__.py"
) + [ROOT / "deploy_all.py"]

# The dataset ships committed so the demo reproduces with no tenant.
EXPECTED_ROWS = {
    "dim_advertiser": 5,
    "dim_brand": 10,
    "dim_market": 5,
    "dim_channel": 7,
    "dim_media_owner": 6,
    "dim_campaign": 80,
    "dim_date": 365,
    "fact_plan": 720,
    "fact_delivery": 21960,
    "fact_billing": 657,
    "pacing_events": 20160,
}

# advertiser, market, quarter -> delivered/planned impression delta, in percent.
# These are the demo. They are exact by construction (normalised daily weights),
# so the number the agent returns can be challenged by hand in the room.
EXPECTED_ANOMALIES = {
    ("ADV-001", "MKT-ES", "2026-Q3"): +12.0,   # Contoso  — make-good clause exists
    ("ADV-004", "MKT-UK", "2026-Q3"): +11.0,   # Litware  — compensation expressly excluded
    ("ADV-002", "MKT-IT", "2026-Q3"): -8.0,    # Fabrikam — 2 % penalty triggered
}
ANOMALY_TOLERANCE_PP = 0.05     # percentage points
BASELINE_MAX_ABS_PP = 4.0       # every other combo must stay clearly below the signal


# ── Static checks ───────────────────────────────────────────────
@pytest.mark.parametrize("py", PY_FILES, ids=lambda p: p.name)
def test_python_compiles(py):
    ast.parse(py.read_text(encoding="utf-8"), filename=str(py))


def test_config_example_parses_and_has_keys():
    cfg = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    for key in ["workspace_name", "capacity_id", "capacity_region", "fabric_api_base",
                "lakehouse_name", "ontology_name", "report_name", "foundry",
                "demo_question_advertiser", "demo_question_market", "demo_question_quarter",
                "anomalies", "generation", "advertisers", "brands", "markets",
                "channels", "media_owners", "kql_tables"]:
        assert key in cfg, f"config.example.yaml missing '{key}'"

    assert cfg["capacity_region"] == cfg["foundry"]["region"], (
        "Fabric capacity and Foundry project must sit in the same region — a cross-region "
        "data agent tool call adds a hop to an already multi-hop path."
    )


def test_config_example_carries_no_real_guids():
    text = (ROOT / "config.example.yaml").read_text(encoding="utf-8")
    assert "<YOUR_FABRIC_CAPACITY_ID>" in text
    assert "<YOUR_TENANT_ID>" in text


# ── Dataset shape ───────────────────────────────────────────────
@pytest.fixture(scope="module")
def tables():
    missing = [n for n in EXPECTED_ROWS if not (RAW / f"{n}.csv").exists()]
    assert not missing, f"missing generated CSVs: {missing} — run `python -m design.notebooks.generate_data`"
    return {n: pd.read_csv(RAW / f"{n}.csv") for n in EXPECTED_ROWS}


@pytest.mark.parametrize("name,rows", sorted(EXPECTED_ROWS.items()))
def test_row_counts(tables, name, rows):
    assert len(tables[name]) == rows


def test_referential_integrity(tables):
    campaigns = set(tables["dim_campaign"]["campaign_id"])
    for fact in ["fact_plan", "fact_delivery", "fact_billing"]:
        orphans = set(tables[fact]["campaign_id"]) - campaigns
        assert not orphans, f"{fact} references unknown campaigns: {sorted(orphans)[:5]}"

    advertisers = set(tables["dim_advertiser"]["advertiser_id"])
    assert set(tables["dim_campaign"]["advertiser_id"]) <= advertisers


# ── The demo storyline ──────────────────────────────────────────
@pytest.fixture(scope="module")
def delivery_vs_plan(tables):
    """delivered/planned impressions per advertiser x market x quarter, in percent."""
    dims = tables["dim_campaign"][["campaign_id", "advertiser_id", "market_id", "quarter"]]
    plan = (tables["fact_plan"].merge(dims, on="campaign_id")
            .groupby(["advertiser_id", "market_id", "quarter"])["planned_impressions"].sum())
    delivered = (tables["fact_delivery"].merge(dims, on="campaign_id")
                 .groupby(["advertiser_id", "market_id", "quarter"])["impressions"].sum())
    return ((delivered / plan) - 1.0) * 100.0


@pytest.mark.parametrize("key,expected", sorted(EXPECTED_ANOMALIES.items()))
def test_planted_anomaly_is_exact(delivery_vs_plan, key, expected):
    assert key in delivery_vs_plan.index, f"anomaly slice {key} absent from the dataset"
    actual = delivery_vs_plan.loc[key]
    assert abs(actual - expected) <= ANOMALY_TOLERANCE_PP, (
        f"{key}: expected {expected:+.2f}%, got {actual:+.2f}%. "
        "The demo answer is no longer hand-checkable."
    )


def test_baseline_stays_below_the_signal(delivery_vs_plan):
    """Anomalies must stand out. Noise elsewhere has to be visibly smaller."""
    noise = delivery_vs_plan.drop(index=list(EXPECTED_ANOMALIES.keys()))
    worst = noise.abs().max()
    assert worst < BASELINE_MAX_ABS_PP, (
        f"background noise reaches {worst:.2f}pp — the planted anomalies no longer stand out"
    )


def test_spend_tracks_plan_despite_impression_gaps(delivery_vs_plan, tables):
    """Over-delivery means more inventory for the same money.

    If spend moved with impressions, the make-good clause would be the wrong
    contractual question and the whole demo premise would collapse.
    """
    dims = tables["dim_campaign"][["campaign_id", "advertiser_id", "market_id", "quarter"]]
    plan = (tables["fact_plan"].merge(dims, on="campaign_id")
            .groupby(["advertiser_id", "market_id", "quarter"])["planned_budget_eur"].sum())
    spent = (tables["fact_delivery"].merge(dims, on="campaign_id")
             .groupby(["advertiser_id", "market_id", "quarter"])["spend_net_eur"].sum())
    spend_delta = ((spent / plan) - 1.0) * 100.0

    for key in EXPECTED_ANOMALIES:
        assert abs(spend_delta.loc[key]) < 3.0, (
            f"{key}: spend moved {spend_delta.loc[key]:+.2f}% with the impressions. "
            "Over-delivery must be free inventory, not extra budget."
        )


def test_unbilled_delivery_gap_is_a_real_anti_join(tables):
    """Delivered months with no invoice row at all — not a status flag.

    Finding it must require LEFT JOIN ... WHERE invoice IS NULL, so a filter on
    invoice_status cannot shortcut the demo.
    """
    delivery = tables["fact_delivery"].copy()
    delivery["month"] = delivery["date_key"].str.slice(0, 7)
    delivered = (delivery.groupby(["campaign_id", "month"], as_index=False)["spend_net_eur"].sum())

    joined = delivered.merge(
        tables["fact_billing"][["campaign_id", "month", "invoice_id"]],
        on=["campaign_id", "month"], how="left",
    )
    gap = joined[joined["invoice_id"].isna()]

    assert len(gap) == 2, f"expected 2 unbilled campaign-months, found {len(gap)}"

    dims = tables["dim_campaign"].set_index("campaign_id")
    for campaign_id in gap["campaign_id"]:
        assert dims.loc[campaign_id, "advertiser_id"] == "ADV-004"
        assert dims.loc[campaign_id, "market_id"] == "MKT-UK"
    assert set(gap["month"]) == {"2026-09"}

    value = gap["spend_net_eur"].sum()
    assert 600_000 < value < 700_000, f"unbilled value {value:,.0f} EUR is off-story"

    # No status flag may leak the answer.
    assert "Unbilled" not in set(tables["fact_billing"]["invoice_status"])


# ── Contracts: the other half of every answer ───────────────────
def test_every_advertiser_has_a_contract(tables):
    files = {p.name for p in CONTRACTS.glob("*.md")}
    for advertiser_id in sorted(tables["dim_advertiser"]["advertiser_id"]):
        assert any(f.startswith(advertiser_id) for f in files), \
            f"no contract file for {advertiser_id}"


@pytest.mark.parametrize("advertiser_id,must_contain", [
    ("ADV-001", ["make-good", "Compensation credit", "45 days"]),
    ("ADV-002", ["fixed penalty equal to 2 %", "net media budget"]),
    ("ADV-004", ["No compensation", "120 days"]),
])
def test_contract_clauses_carry_the_storyline(advertiser_id, must_contain):
    """The clauses must stay divergent.

    Contoso (+12 %) gets a credit, Litware (+11 %) gets nothing, Fabrikam (-8 %)
    owes a penalty. Harmonise these and the demo proves nothing.
    """
    path = next(CONTRACTS.glob(f"{advertiser_id}-*.md"))
    text = path.read_text(encoding="utf-8")
    for needle in must_contain:
        assert needle in text, f"{path.name} no longer states '{needle}'"


def test_contracts_are_marked_fictional():
    for path in sorted(CONTRACTS.glob("*.md")):
        head = path.read_text(encoding="utf-8")[:400]
        assert "fictional" in head, f"{path.name} lacks its fictional-document notice"
