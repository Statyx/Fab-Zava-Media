"""
Tests for the Power BI report.

These assert on the GENERATED PBIR folder, not on the generator's source. The
distinction matters: every failure below deploys cleanly and validates cleanly.
A report that hangs forever on "Loading your report..." passes
`powerbi-report-author validate` with 0 errors, and so does a report whose 27
visuals were never validated at all because their $schema 404s.

Each test corresponds to a numbered entry in
Azure-Brain/Fabric-Brain/agents/report-builder-agent/known_issues.md.

No tenant and no network needed — the folder on disk is the whole subject.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "fabric" / "powerbi" / "Zava_Media_Report.Report"
DEFN = REPORT / "definition"
PAGES = DEFN / "pages"

CANVAS_W, CANVAS_H = 1280, 720

# Visuals that render nothing from the model. Issue 9: a query here is rejected.
NON_DATA_VISUALS = {
    "textbox", "shape", "image", "basicShape",
    "actionButton", "bookmarkNavigator", "pageNavigator",
}

pytestmark = pytest.mark.skipif(
    not REPORT.exists(),
    reason="report not generated yet — run `python -m fabric.powerbi.deploy_report --build-only`",
)


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def visual_files() -> list[Path]:
    return sorted(PAGES.glob("*/visuals/*/visual.json"))


def page_files() -> list[Path]:
    return sorted(PAGES.glob("*/page.json"))


# ── issue 19-bis + 21 ─────────────────────────────────────────────────────────

def test_visual_schema_version_exists_upstream():
    """
    visualContainer 2.10.0 and up return 404 from the schema host (measured
    2026-09-02). That is not a broken link, it is a disabled check: the CLI
    reports an unreachable schema as a WARNING, skips every file pinned to it,
    and still prints "result":"succeeded" with errorCount 0.

    So the danger is not that validation fails. It is that it passes.
    """
    dead = {"2.10.0", "2.11.0", "2.12.0", "2.13.0", "2.14.0"}
    for f in visual_files():
        schema = _load(f)["$schema"]
        version = schema.rsplit("/schema.json", 1)[0].rsplit("/", 1)[-1]
        assert version not in dead, (
            f"{f.parent.name} pins visualContainer/{version}, which 404s. "
            f"The CLI will skip this file and still report success. Use 2.9.0."
        )
        assert version == "2.9.0", (
            f"{f.parent.name} pins visualContainer/{version}. Only 2.5.0 and "
            f"2.9.0 resolve; 2.9.0 is the newest and is what report.json "
            f"declares in reportVersionAtImport.visual."
        )


def test_every_schema_url_is_pinned_and_absolute():
    for f in list(visual_files()) + list(page_files()) + [
        DEFN / "report.json", DEFN / "version.json", PAGES / "pages.json"
    ]:
        schema = _load(f).get("$schema", "")
        assert schema.startswith("https://developer.microsoft.com/json-schemas/"), f
        assert schema.endswith("/schema.json"), f


# ── issue 23 ──────────────────────────────────────────────────────────────────

def test_pages_carry_no_ordinal():
    """page schema 2.1.0 is closed: `ordinal` is rejected outright. Tab order
    is owned by pages.json -> pageOrder and nothing else."""
    for f in page_files():
        assert "ordinal" not in _load(f), (
            f"{f.parent.name}/page.json has `ordinal` — schema 2.1.0 rejects it "
            f"as an additional property."
        )


# ── issue 19: the four anti-hang conditions ───────────────────────────────────

def test_version_is_two_zero_zero():
    assert _load(DEFN / "version.json")["version"] == "2.0.0", (
        "version.json must be 2.0.0. 4.0.0 validates fine and hangs the renderer."
    )


def test_report_json_has_the_three_required_blocks():
    r = _load(DEFN / "report.json")
    for key in ("reportSource", "settings", "objects"):
        assert key in r, f"report.json is missing `{key}` — the renderer hangs without it."


def test_base_theme_is_a_real_builtin_and_ships_its_json():
    r = _load(DEFN / "report.json")
    name = r["themeCollection"]["baseTheme"]["name"]
    themes = REPORT / "StaticResources" / "SharedResources" / "BaseThemes"
    shipped = {p.stem for p in themes.glob("*.json")}
    assert name in shipped, (
        f"baseTheme `{name}` has no json in BaseThemes/ (found: {sorted(shipped)}). "
        f"A custom-named baseTheme hangs the renderer."
    )
    declared = {
        i["path"] for pkg in r.get("resourcePackages", []) for i in pkg.get("items", [])
    }
    assert f"BaseThemes/{name}.json" in declared, (
        f"the theme file exists but report.json -> resourcePackages does not "
        f"declare it; the renderer looks it up there, not on disk."
    )


def test_no_custom_theme_alongside_the_base_theme():
    """`customTheme` + RegisteredResources is the combination that hangs. The
    base theme has to stand alone."""
    r = _load(DEFN / "report.json")
    assert "customTheme" not in r.get("themeCollection", {})
    assert all(
        pkg.get("type") != "RegisteredResources" for pkg in r.get("resourcePackages", [])
    )


# ── issue 4 ───────────────────────────────────────────────────────────────────

def test_every_page_folder_appears_in_page_order():
    order = _load(PAGES / "pages.json")["pageOrder"]
    on_disk = {f.parent.name for f in page_files()}
    assert on_disk == set(order), (
        f"pageOrder {order} does not match folders {sorted(on_disk)} — "
        f"a page missing from pageOrder is invisible, with no error anywhere."
    )
    assert _load(PAGES / "pages.json")["activePageName"] in order


# ── issue 11 ──────────────────────────────────────────────────────────────────

def test_no_visual_falls_off_the_canvas():
    for f in visual_files():
        p = _load(f)["position"]
        assert p["x"] + p["width"] <= CANVAS_W, f"{f.parent.name} overflows right edge"
        assert p["y"] + p["height"] <= CANVAS_H, f"{f.parent.name} overflows bottom edge"
        assert p["x"] >= 0 and p["y"] >= 0, f"{f.parent.name} has a negative origin"


# ── issue 9 ───────────────────────────────────────────────────────────────────

def test_non_data_visuals_carry_no_query():
    for f in visual_files():
        v = _load(f)["visual"]
        if v["visualType"] in NON_DATA_VISUALS:
            assert not v.get("query"), (
                f"{f.parent.name} is a {v['visualType']} and carries a query — "
                f"strip it; it has nothing to bind to."
            )


# ── issue 16 ──────────────────────────────────────────────────────────────────

def test_cards_are_tall_enough_and_size_their_own_callout():
    """A card under 120px clips the number it exists to show, and the fontSize
    must sit on the visual — cardCalloutArea has no fontSize property at all."""
    for f in visual_files():
        d = _load(f)
        if d["visual"]["visualType"] != "cardVisual":
            continue
        assert d["position"]["height"] >= 120, (
            f"{f.parent.name} is {d['position']['height']}px tall — the callout clips."
        )
        objs = d["visual"].get("objects", {})
        assert "value" in objs, f"{f.parent.name} has no explicit value.fontSize"
        props = objs["value"][0]["properties"]
        assert "fontSize" in props, (
            f"{f.parent.name} does not set value.fontSize. Do not reach for "
            f"cardCalloutArea.fontSize — that property does not exist."
        )


# ── the demo's own claim ──────────────────────────────────────────────────────

def test_the_central_claim_is_on_the_canvas():
    """
    The demo says one answer needs a NUMBER computed in Fabric crossed with a
    CONTRACT CLAUSE retrieved by Foundry. If that sentence lives only in the
    slides, the report is just another dashboard. It has to be readable on the
    page a customer is looking at.
    """
    claim = PAGES / "billing_rebates" / "visuals" / "txt_demo_claim" / "visual.json"
    assert claim.exists(), "the textbox stating the demo's claim is gone"
    text = json.dumps(_load(claim)).lower()
    assert "contract" in text and "fabric" in text, (
        "the claim textbox no longer names both halves of the demo"
    )
