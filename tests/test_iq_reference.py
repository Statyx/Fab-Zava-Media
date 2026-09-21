"""The visual comparison must not invent either its data or its ontology bindings."""
import json

import pytest

from design.notebooks.export_iq_reference import (
    OUTPUT, build_reference, ontology_scope, read_tables, tabular_scope,
)


def test_generated_reference_is_current():
    assert json.loads(OUTPUT.read_text(encoding="utf-8")) == build_reference()


def test_both_paths_match_for_every_owner_and_quarter():
    reference = build_reference()
    for owner in {r["mediaOwnerId"] for r in reference["tabular"]}:
        for quarter in ("2026-Q2", "2026-Q3"):
            scope = lambda rows: [r for r in rows if r["mediaOwnerId"] == owner and r["quarter"] == quarter]
            left, right = scope(reference["tabular"]), scope(reference["ontology"])
            assert left and left == right
            assert len(left) == len({r["campaignId"] for r in left})


def test_repeated_placements_do_not_duplicate_campaigns():
    tables = read_tables()
    expected = tabular_scope(tables)
    tables["fact_plan"] += tables["fact_plan"][:20]
    assert tabular_scope(tables) == ontology_scope(tables) == expected


def test_missing_identity_fails_instead_of_shortening_the_graph_silently():
    tables = read_tables()
    tables["dim_advertiser"] = tables["dim_advertiser"][1:]
    with pytest.raises(ValueError, match="Dangling"):
        ontology_scope(tables)
    with pytest.raises(KeyError):
        tabular_scope(tables)
