import json

import pytest

from design.notebooks.export_iq_dossiers import OUTPUT, WORK_NOTES, WEB_OUTPUT, WEB_NOTES, article, build_dossiers, build_web_context


def test_generated_dossiers_are_current():
    assert json.loads(OUTPUT.read_text(encoding="utf-8")) == build_dossiers()


def test_existing_measurements_and_contracts_remain_distinct():
    contoso, litware = build_dossiers()["cases"]
    assert contoso["facts"]["variance"] == pytest.approx(0.12, abs=0.0005)
    assert litware["facts"]["variance"] == pytest.approx(0.11, abs=0.0005)
    assert contoso["contract"]["treatment"] == "credit"
    assert litware["contract"]["treatment"] == "excluded"
    credit = next(a["text"] for a in contoso["contract"]["articles"] if a["number"] == "6.2")
    assert "compensation credit" in credit and "45 days" in credit
    assert "50 %" in credit and "10 %" in credit
    exclusion = next(a["text"] for a in litware["contract"]["articles"] if a["number"] == "6.1")
    assert "No compensation, no credit and no penalty" in exclusion
    assert not set(contoso["campaignIds"]) & set(litware["campaignIds"])


def test_work_context_is_fictional_and_no_approval_is_invented():
    work = json.loads(WORK_NOTES.read_text(encoding="utf-8"))
    assert work["simulated"] is True
    assert all(n["simulated"] is True for n in work["notes"])
    assert all(n["status"] == "prepared-awaiting-validation" for n in work["notes"])
    assert all("pending" in n["text"] for n in work["notes"])
    assert work["asOf"] > "2026-09-30"


def test_missing_contract_article_fails():
    with pytest.raises(ValueError, match="Missing contract article"):
        article("A document with no clause", "6.2")


def test_web_context_is_current_fictional_and_separate_from_measured_evidence():
    dossiers = build_dossiers()
    context = build_web_context(dossiers)
    assert json.loads(WEB_OUTPUT.read_text(encoding="utf-8")) == context
    assert context["simulated"] is True
    assert len(context["notes"]) == 2
    assert {n["caseId"] for n in context["notes"]} == {c["id"] for c in dossiers["cases"]}
    for note in context["notes"]:
        assert note["simulated"] is True
        assert "(fictional)" in note["source"]
        assert note["publishedOn"] <= context["asOf"]
        assert not any("http" in str(v) for v in note.values())
    # The real recorder inputs do not gain fictitious public news or require recapture.
    assert "webNotes" not in dossiers
    capture = json.loads((OUTPUT.parent / "iq-dossier-capture.generated.json").read_text(encoding="utf-8"))
    assert capture["fingerprint"] == dossiers["fingerprint"]


@pytest.mark.parametrize("key,value", [
    ("simulated", False), ("marketId", "MKT-UK"), ("publishedOn", "2026-10-16"),
    ("caseId", "unknown-case"), ("headline", ""), ("publishedOn", "2026-02-30"),
])
def test_invalid_web_notice_fails_export(monkeypatch, tmp_path, key, value):
    context = json.loads(WEB_NOTES.read_text(encoding="utf-8"))
    context["notes"][0][key] = value
    path = tmp_path / "web-notes.json"
    path.write_text(json.dumps(context), encoding="utf-8")
    monkeypatch.setattr("design.notebooks.export_iq_dossiers.WEB_NOTES", path)
    with pytest.raises(ValueError):
        build_web_context(build_dossiers())
