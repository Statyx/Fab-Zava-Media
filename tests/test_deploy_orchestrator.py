"""Offline regressions for the full Fabric + Foundry + application deploy scope."""

import argparse
import sys

import pytest

import deploy_all


def plan(**overrides):
    args = argparse.Namespace(
        steps=[], from_step=None, skip=None,
        fabric_only=False, foundry_only=False, app_only=False,
    )
    for name, value in overrides.items():
        setattr(args, name, value)
    return deploy_all.select_steps(args)


def test_default_chain_deploys_application_last():
    assert plan() == deploy_all.STEP_NAMES
    assert plan()[-2:] == ["foundry_agents", "application"]
    assert dict(deploy_all.STEPS)["application"] == "fabric.application.deploy_application"


@pytest.mark.parametrize("scope, expected", [
    ("fabric_only", deploy_all.FABRIC_STEPS),
    ("foundry_only", deploy_all.FOUNDRY_STEPS),
    ("app_only", deploy_all.APPLICATION_STEPS),
])
def test_scope_filter_selects_only_its_steps(scope, expected):
    assert plan(**{scope: True}) == expected


@pytest.mark.parametrize("options, expected", [
    ({"steps": ["application"]}, ["application"]),
    ({"from_step": "application"}, ["application"]),
    ({"from_step": "foundry_agents"}, ["foundry_agents", "application"]),
    ({"from_step": "foundry_agents", "app_only": True}, ["application"]),
    ({"steps": ["application", "workspace"]}, ["workspace", "application"]),
    ({"steps": ["application", "workspace"], "fabric_only": True}, ["workspace"]),
    ({"steps": ["application", "foundry_agents"], "foundry_only": True}, ["foundry_agents"]),
    ({"skip": "application"}, deploy_all.STEP_NAMES[:-1]),
])
def test_application_respects_ranges_filters_and_skip(options, expected):
    assert plan(**options) == expected


@pytest.mark.parametrize("options", [
    {"from_step": "application", "fabric_only": True},
    {"from_step": "application", "foundry_only": True},
    {"steps": ["application"], "fabric_only": True},
    {"steps": ["application"], "foundry_only": True},
    {"steps": ["workspace"], "app_only": True},
    {"app_only": True, "skip": "application"},
])
def test_empty_scope_fails_loudly(options):
    with pytest.raises(SystemExit, match="Nothing to run"):
        plan(**options)


@pytest.mark.parametrize("first, second", [
    ("fabric_only", "foundry_only"),
    ("fabric_only", "app_only"),
    ("foundry_only", "app_only"),
])
def test_scope_flags_are_mutually_exclusive(first, second):
    with pytest.raises(SystemExit, match="mutually exclusive"):
        plan(**{first: True, second: True})


@pytest.mark.parametrize("flags", [
    ["--fabric-only", "--foundry-only"],
    ["--fabric-only", "--app-only"],
    ["--foundry-only", "--app-only"],
])
def test_cli_rejects_conflicting_scopes_before_auth(flags, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["deploy_all.py", *flags])
    monkeypatch.setattr(deploy_all, "load_config", lambda: pytest.fail("Must not authenticate"))
    with pytest.raises(SystemExit) as exc:
        deploy_all.main()
    assert exc.value.code == 2


@pytest.mark.parametrize("flags, expected", [
    ([], deploy_all.STEP_NAMES),
    (["application"], ["application"]),
    (["--from", "application"], ["application"]),
    (["--app-only"], ["application"]),
    (["--fabric-only"], deploy_all.FABRIC_STEPS),
    (["--foundry-only"], deploy_all.FOUNDRY_STEPS),
    (["--skip", "application"], deploy_all.STEP_NAMES[:-1]),
])
def test_main_reports_actual_deployment_scope(flags, expected, monkeypatch, capsys):
    state = {"application_url": "https://old-app.example.test"}
    actual_url = "https://deployed-app.example.test"
    ran = []

    def run_steps(names):
        ran.extend(names)
        if "application" in names:
            state["application_url"] = actual_url

    monkeypatch.setattr(sys, "argv", ["deploy_all.py", *flags, "--no-warmup"])
    monkeypatch.setattr(deploy_all, "load_config", lambda: {})
    monkeypatch.setattr(deploy_all, "ensure_tenant", lambda cfg: None)
    monkeypatch.setattr(deploy_all, "load_state", lambda: dict(state))
    monkeypatch.setattr(deploy_all, "run_steps", run_steps)
    monkeypatch.setattr(deploy_all, "warm_up", lambda *args: pytest.fail("Warm-up disabled"))

    deploy_all.main()

    assert ran == expected
    output = capsys.readouterr().out
    assert "ready" not in output.lower()
    assert "old-app.example.test" not in output
    if "application" in expected:
        assert actual_url in output
        assert "still require validation" in output
        assert "application not deployed" not in output
    else:
        assert "application not deployed in this run" in output
        assert "not a complete tenant migration" in output
        assert "Hosted application:" not in output
    assert ("Full deployment steps completed" in output) == (expected == deploy_all.STEP_NAMES)


def test_application_without_url_cannot_claim_completion(capsys):
    with pytest.raises(RuntimeError, match="application_url"):
        deploy_all.print_deployment_summary(deploy_all.STEP_NAMES, {})
    assert "completed" not in capsys.readouterr().out


def test_warmup_only_never_claims_deployment(monkeypatch, capsys):
    warmed = []
    monkeypatch.setattr(sys, "argv", ["deploy_all.py", "--warmup"])
    monkeypatch.setattr(deploy_all, "load_config", lambda: {})
    monkeypatch.setattr(deploy_all, "ensure_tenant", lambda cfg: None)
    monkeypatch.setattr(deploy_all, "load_state", lambda: {})
    monkeypatch.setattr(deploy_all, "run_steps", lambda names: pytest.fail("Warm-up only"))
    monkeypatch.setattr(deploy_all, "warm_up", lambda cfg, state: warmed.append(True))
    deploy_all.main()
    assert warmed == [True]
    assert "deployment" not in capsys.readouterr().out.lower()
