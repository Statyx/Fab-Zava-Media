"""Offline guards for the application side of a tenant migration."""
import json

import pytest

from fabric.application import deploy_application as deploy


def bindings():
    return deploy.app_bindings(
        {"tenant_id": "new-tenant"},
        {
            "application_client_id": "new-client", "workspace_id": "new-workspace",
            "semantic_model_id": "new-model", "graph_model_id": "new-graph",
            "data_agent_id": "new-agent",
            "foundry_endpoint": "https://target.services.ai.azure.com/api/projects/demo",
            "foundry_supervisor_agent": "supervisor",
        },
    )


def test_app_bindings_come_from_current_state():
    env = bindings()
    assert env["VITE_ENTRA_TENANT_ID"] == "new-tenant"
    assert env["VITE_ZAVA_WORKSPACE_ID"] == "new-workspace"
    assert env["VITE_SEMANTIC_MODEL_ID"] == "new-model"
    assert len(env) == 8
    assert not any("SECRET" in key or "TOKEN" in key for key in env)


def test_mode_files_cannot_override_new_rayfin_target(tmp_path):
    old = (
        "VITE_ENTRA_TENANT_ID=old-tenant\nVITE_SEMANTIC_MODEL_ID=old-model\n"
        "VITE_FABRIC_ITEM_ID=old-item\nVITE_RAYFIN_API_URL=https://old.invalid\n"
        "UNRELATED_OPTION=preserve\n"
    )
    for mode in ("development", "production"):
        (tmp_path / f".env.{mode}.local").write_text(old)
    (tmp_path / ".env.local").write_text(
        "VITE_FOUNDRY_ENDPOINT=https://old.invalid\nVITE_PORT=5173\n",
    )
    deploy.write_bindings(bindings(), tmp_path)
    deploy.write_bindings(bindings(), tmp_path)
    for mode in ("development", "production"):
        content = (tmp_path / f".env.{mode}.local").read_text()
        assert "old-" not in content and "old.invalid" not in content
        assert "VITE_FABRIC_ITEM_ID" not in content
        assert content.count("VITE_ENTRA_TENANT_ID=") == 1
        assert "UNRELATED_OPTION=preserve" in content
        assert (tmp_path / f".env.{mode}.before-migration.local").read_text() == old
    assert (tmp_path / ".env.local").read_text() == "VITE_PORT=5173\n"


def test_same_named_workspaces_preserve_previous_deployment(tmp_path):
    path = tmp_path / ".deployments.json"
    original = {"fabricTenantId": "old", "fabricWorkspaceId": "old-workspace",
                "fabricItemId": "old-app", "hostingUrl": "https://old.invalid"}
    path.write_text(json.dumps({"active": "zava-media", "deployments": {"zava-media": original}}))
    deploy.preserve_deployments(path)
    deploy.preserve_deployments(path)
    registry = json.loads(path.read_text())
    assert registry["deployments"]["zava-media--old--old-workspace"] == original
    assert registry["deployments"]["zava-media"] == original
    assert len(registry["deployments"]) == 2
    assert registry["active"] == "zava-media"


def test_wrong_rayfin_target_is_never_accepted(tmp_path):
    path = tmp_path / ".deployments.json"
    path.write_text(json.dumps({"active": "old", "deployments": {"old": {
        "fabricTenantId": "old", "fabricWorkspaceId": "workspace",
    }}}))
    with pytest.raises(RuntimeError, match="approved tenant"):
        deploy.target_deployment(
            {"tenant_id": "new"}, {"workspace_id": "workspace"}, path,
        )


def test_name_collision_releases_only_old_alias_not_old_deployment(tmp_path):
    path = tmp_path / ".deployments.json"
    original = {"fabricTenantId": "old", "fabricWorkspaceId": "old-workspace",
                "fabricItemId": "old-app"}
    path.write_text(json.dumps({"active": "zava-media", "deployments": {
        "zava-media": original, "other-project": original,
    }}))
    deploy.preserve_deployments(path, "zava-media", "new", "new-workspace")
    deploy.preserve_deployments(path, "zava-media", "new", "new-workspace")
    registry = json.loads(path.read_text())
    assert "zava-media" not in registry["deployments"]
    assert registry["deployments"]["zava-media--old--old-workspace"] == original
    assert registry["deployments"]["other-project"] == original
    assert registry["active"] == "zava-media--old--old-workspace"


def test_matching_target_alias_is_reused(tmp_path):
    path = tmp_path / ".deployments.json"
    record = {"fabricTenantId": "target", "fabricWorkspaceId": "workspace",
              "fabricItemId": "app"}
    path.write_text(json.dumps({"active": "zava-media", "deployments": {"zava-media": record}}))
    deploy.preserve_deployments(path, "zava-media", "target", "workspace")
    registry = json.loads(path.read_text())
    assert registry["deployments"]["zava-media"] == record
    assert registry["active"] == "zava-media"


def test_preflight_rejects_wrong_cli_tenant_before_remote_calls(monkeypatch):
    monkeypatch.setattr(deploy, "az_json", lambda _: {"tenantId": "old", "id": "subscription"})
    state = {key: "present" for key in ("workspace_id", "semantic_model_id", "graph_model_id",
                                       "data_agent_id", "foundry_endpoint", "foundry_supervisor_agent")}
    with pytest.raises(RuntimeError, match="Wrong Azure tenant"):
        deploy.preflight({"tenant_id": "new"}, state)


def test_permissions_are_only_delegated_and_resolved_not_hardcoded(monkeypatch):
    def graph_call(_token, method, path, **kwargs):
        assert method == "GET"
        return {"value": [{
            "id": "service-principal", "appId": "resource-app",
            "oauth2PermissionScopes": [
                {"id": scope, "value": scope, "isEnabled": True}
                for scopes in deploy.PERMISSIONS.values() for scope in scopes
            ],
        }]}
    monkeypatch.setattr(deploy, "graph_call", graph_call)
    for _, scopes, resource in deploy.discover_permissions("not-a-real-token"):
        assert {entry["id"] for entry in resource["resourceAccess"]} == set(scopes)
        assert all(entry["type"] == "Scope" for entry in resource["resourceAccess"])


def test_redirects_preserve_existing_entries_and_reject_untrusted_hosts(monkeypatch):
    calls = []
    def graph_call(_token, method, path, **kwargs):
        calls.append((method, kwargs))
        if method == "GET":
            return {"spa": {"redirectUris": ["http://localhost:5173/blank.html"]}}
    monkeypatch.setattr(deploy, "graph_call", graph_call)
    host = "https://sample-swedencentral.webapp.fabricapps.net"
    assert deploy.update_redirects("token", {"id": "app"}, host) == host
    assert calls[-1][1]["json"]["spa"]["redirectUris"] == sorted([
        "http://localhost:5173/blank.html", host, host + "/blank.html",
    ])
    with pytest.raises(RuntimeError, match="Unexpected"):
        deploy.update_redirects("token", {"id": "app"}, "https://untrusted.example")
