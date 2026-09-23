#!/usr/bin/env python3
"""Deploy the React/Rayfin Fabric App against the same tenant and state as its backend.

Run ``python -m fabric.application.deploy_application --check`` for read-only preflight.
The default creates/reuses a single-tenant SPA, grants the deploying user delegated
access, provisions Rayfin, configures its redirect URI, and publishes a fresh build.
No client secret is created; the Fabric deployment token stays in the child environment.
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import argparse
import json
import shutil
import subprocess
from urllib.parse import urlparse

import requests

from fabric._shared.helpers import (
    load_config, load_state, require_config, require_state, save_state,
)
from fabric._shared.paths import ROOT
from fabric._shared.platform_env import AZ_NEEDS_SHELL, find_executable

APP = ROOT / "app"
GRAPH = "https://graph.microsoft.com/v1.0"
FABRIC_RESOURCE = "https://api.fabric.microsoft.com"
PERMISSIONS = {
    "https://analysis.windows.net/powerbi/api": (
        "Dataset.Read.All", "Item.Read.All", "DataAgent.Execute.All",
    ),
    "https://ai.azure.com": ("user_impersonation",),
}


def az_json(args):
    result = subprocess.run(
        ["az", *args, "-o", "json"], shell=AZ_NEEDS_SHELL,
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Azure CLI command failed.")
    return json.loads(result.stdout)


def token_for(resource, tenant):
    result = az_json([
        "account", "get-access-token", "--tenant", tenant, "--resource", resource,
    ])
    if result.get("tenant", "").lower() != tenant.lower():
        raise RuntimeError("Azure CLI returned a token for a different tenant.")
    return result["accessToken"]


def graph_call(token, method, path, **kwargs):
    response = requests.request(
        method, f"{GRAPH}/{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60, **kwargs,
    )
    if not response.ok:
        raise RuntimeError(f"Microsoft Graph {method} {path}: {response.status_code} {response.text}")
    return response.json() if response.content else None


def preflight(cfg, state):
    tenant = require_config(cfg, "tenant_id")
    workspace = require_state(state, "workspace_id")
    for key in ("semantic_model_id", "graph_model_id", "data_agent_id",
                "foundry_endpoint", "foundry_supervisor_agent"):
        require_state(state, key)
    account = az_json(["account", "show"])
    if account["tenantId"].lower() != tenant.lower():
        raise RuntimeError("Wrong Azure tenant. Sign in and select the configured subscription first.")
    if state.get("foundry_subscription_id") != account["id"]:
        raise RuntimeError("Foundry state belongs to a different subscription.")
    for key, expected in (("application_tenant_id", tenant),
                          ("application_workspace_id", workspace)):
        if state.get(key) and state[key] != expected:
            raise RuntimeError(f"{key} belongs to a different deployment; isolate its state first.")
    endpoint = urlparse(state["foundry_endpoint"])
    if endpoint.scheme != "https" or not endpoint.hostname or not endpoint.hostname.endswith(".services.ai.azure.com"):
        raise RuntimeError("Expected an HTTPS Foundry project endpoint.")
    if not (APP / "node_modules" / "@microsoft" / "rayfin-cli" / "scripts" / "main").exists():
        raise RuntimeError("Application dependencies missing. Run npm ci in app first.")
    if not find_executable("node"):
        raise RuntimeError("Node.js is required to deploy the Fabric App.")

    token = token_for(FABRIC_RESOURCE, tenant)
    api = cfg["fabric_api_base"].rstrip("/")
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{api}/workspaces/{workspace}", headers=headers, timeout=60)
    response.raise_for_status()
    if response.json().get("capacityId", "").lower() != require_config(cfg, "capacity_id").lower():
        raise RuntimeError("The application workspace is not on the configured capacity.")
    response = requests.get(f"{api}/workspaces/{workspace}/items", headers=headers, timeout=60)
    response.raise_for_status()
    items = response.json()
    ids = {item["id"] for item in items.get("value", [])}
    while items.get("continuationToken"):
        response = requests.get(
            f"{api}/workspaces/{workspace}/items", headers=headers,
            params={"continuationToken": items["continuationToken"]}, timeout=60,
        )
        response.raise_for_status()
        items = response.json()
        ids.update(item["id"] for item in items.get("value", []))
    for key in ("semantic_model_id", "graph_model_id", "data_agent_id", "report_id"):
        if require_state(state, key) not in ids:
            raise RuntimeError(f"{key} is not present in the target workspace.")
    print(f"Verified tenant {tenant}, workspace {workspace}, capacity and backend item IDs.")
    return tenant, workspace


def discover_permissions(token):
    permissions = []
    for uri, scopes in PERMISSIONS.items():
        matches = graph_call(token, "GET", "servicePrincipals", params={
            "$filter": f"servicePrincipalNames/any(n:n eq '{uri}')",
            "$select": "id,appId,oauth2PermissionScopes",
        })["value"]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one API service principal for {uri}.")
        sp = matches[0]
        available = {p["value"]: p["id"] for p in sp["oauth2PermissionScopes"] if p["isEnabled"]}
        missing = set(scopes) - available.keys()
        if missing:
            raise RuntimeError(f"Delegated scopes unavailable for {uri}: {sorted(missing)}")
        permissions.append((sp, scopes, {
            "resourceAppId": sp["appId"],
            "resourceAccess": [{"id": available[scope], "type": "Scope"} for scope in scopes],
        }))
    return permissions


def ensure_spa(token, cfg, state, tenant, workspace):
    permissions = discover_permissions(token)
    name = cfg.get("application", {}).get("registration_name", "Zava Media Console")
    apps = graph_call(token, "GET", "applications", params={
        "$filter": "displayName eq '" + name.replace("'", "''") + "'",
        "$select": "id,appId,displayName,signInAudience,spa,requiredResourceAccess",
    })["value"]
    if state.get("application_client_id"):
        apps = [a for a in apps if a["appId"] == state["application_client_id"]]
        if not apps:
            raise RuntimeError("The recorded SPA registration is missing; refusing to silently replace it.")
    if len(apps) > 1:
        raise RuntimeError("Multiple matching SPA registrations. Record the intended application_client_id.")
    if apps:
        app = apps[0]
        if app["signInAudience"] != "AzureADMyOrg":
            raise RuntimeError("The SPA must be single-tenant; refusing to modify a shared registration.")
    else:
        app = graph_call(token, "POST", "applications", json={
            "displayName": name,
            "signInAudience": "AzureADMyOrg",
            "spa": {"redirectUris": ["http://localhost:5173/blank.html"]},
            "requiredResourceAccess": [p[2] for p in permissions],
        })
    # Persist immediately so an interrupted consent/hosting step is resumable.
    state.update(application_client_id=app["appId"], application_object_id=app["id"],
                 application_tenant_id=tenant, application_workspace_id=workspace)
    save_state(state)
    merged = {p["resourceAppId"]: p for p in app.get("requiredResourceAccess", [])}
    for _, _, permission in permissions:
        current = merged.setdefault(permission["resourceAppId"], {
            "resourceAppId": permission["resourceAppId"], "resourceAccess": [],
        })
        for scope in permission["resourceAccess"]:
            if scope not in current["resourceAccess"]:
                current["resourceAccess"].append(scope)
    graph_call(token, "PATCH", f"applications/{app['id']}",
               json={"requiredResourceAccess": list(merged.values())})
    principals = graph_call(token, "GET", "servicePrincipals", params={
        "$filter": f"appId eq '{app['appId']}'", "$select": "id",
    })["value"]
    principal = principals[0] if principals else graph_call(
        token, "POST", "servicePrincipals", json={"appId": app["appId"]},
    )
    user = graph_call(token, "GET", "me", params={"$select": "id"})
    grants = graph_call(token, "GET", "oauth2PermissionGrants", params={
        "$filter": f"clientId eq '{principal['id']}'",
    })["value"]
    for resource, scopes, _ in permissions:
        covering = [g for g in grants if g["resourceId"] == resource["id"]
                    and (g["consentType"] == "AllPrincipals" or g.get("principalId") == user["id"])]
        granted = set().union(*(set(g["scope"].split()) for g in covering))
        if set(scopes) <= granted:
            continue
        own = next((g for g in covering if g["consentType"] == "Principal"), None)
        scope = " ".join(sorted(set(scopes) | (set(own["scope"].split()) if own else set())))
        if own:
            graph_call(token, "PATCH", f"oauth2PermissionGrants/{own['id']}", json={"scope": scope})
        else:
            graph_call(token, "POST", "oauth2PermissionGrants", json={
                "clientId": principal["id"], "consentType": "Principal",
                "principalId": user["id"], "resourceId": resource["id"], "scope": scope,
            })
    print(f"SPA {app['appId']}: delegated access consented for the deploying user only.")
    return app


def app_bindings(cfg, state):
    return {
        "VITE_ENTRA_CLIENT_ID": require_state(state, "application_client_id"),
        "VITE_ENTRA_TENANT_ID": require_config(cfg, "tenant_id"),
        "VITE_SEMANTIC_MODEL_ID": require_state(state, "semantic_model_id"),
        "VITE_ZAVA_WORKSPACE_ID": require_state(state, "workspace_id"),
        "VITE_ZAVA_GRAPH_MODEL_ID": require_state(state, "graph_model_id"),
        "VITE_ZAVA_DATA_AGENT_ID": require_state(state, "data_agent_id"),
        "VITE_FOUNDRY_ENDPOINT": require_state(state, "foundry_endpoint"),
        "VITE_FOUNDRY_SUPERVISOR_AGENT": require_state(state, "foundry_supervisor_agent"),
    }


def write_bindings(bindings, app_root=APP):
    for mode in ("production", "development"):
        path = app_root / f".env.{mode}.local"
        if path.exists():
            backup = app_root / f".env.{mode}.before-migration.local"
            if not backup.exists():
                shutil.copy2(path, backup)
        lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
        # Rayfin owns these values in .env.local; old mode overrides must not win.
        managed_prefixes = ("VITE_FABRIC_", "VITE_RAYFIN_")
        lines = [line for line in lines if line.split("=", 1)[0].strip() not in bindings
                 and not line.startswith(managed_prefixes)]
        path.write_text("\n".join([*lines, *(f"{k}={v}" for k, v in bindings.items())]) + "\n",
                        encoding="utf-8")
    local = app_root / ".env.local"
    if local.exists():
        lines = [line for line in local.read_text(encoding="utf-8-sig").splitlines()
                 if line.split("=", 1)[0].strip() not in bindings]
        local.write_text("\n".join(lines) + "\n", encoding="utf-8")


def preserve_deployments(path, target_key=None, tenant=None, workspace=None):
    """Rayfin keys records by workspace NAME; identical names across tenants collide."""
    if not path.exists():
        return
    registry = json.loads(path.read_text(encoding="utf-8-sig"))
    records = registry["deployments"]
    for key, record in list(records.items()):
        if record.get("fabricTenantId") and record.get("fabricWorkspaceId"):
            archive = f"{key.split('--')[0]}--{record['fabricTenantId']}--{record['fabricWorkspaceId']}"
            records.setdefault(archive, record.copy())
            if key == target_key and (
                record["fabricTenantId"] != tenant or record["fabricWorkspaceId"] != workspace
            ):
                # Rayfin 1.34 resolves the name before checking the explicit workspace ID.
                # Keep the old target addressable, but release its colliding name alias.
                del records[key]
                if registry.get("active") == key:
                    registry["active"] = archive
    path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")


def registry_key(workspace_name):
    script = (
        "import {sanitizeWorkspaceName} from "
        "'./node_modules/@microsoft/rayfin-cli/dist/utils/deployments-registry.js';"
        "console.log(sanitizeWorkspaceName(process.argv[1]));"
    )
    return subprocess.check_output(
        [find_executable("node"), "--input-type=module", "-e", script, workspace_name],
        cwd=APP, text=True, encoding="utf-8",
    ).strip()


def rayfin(args, cfg, state):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("VITE_", "RAYFIN_", "AZURE_TOKEN_CREDENTIALS"))}
    env.update(RAYFIN_TOKEN=token_for(FABRIC_RESOURCE, cfg["tenant_id"]),
               RAYFIN_TENANT_ID=cfg["tenant_id"], RAYFIN_WORKSPACE_ID=state["workspace_id"],
               NO_COLOR="1")
    cli = APP / "node_modules" / "@microsoft" / "rayfin-cli" / "scripts" / "main"
    # Invoke the JS entry point directly: no shell, cmd length limit or cached Rayfin login.
    subprocess.run([find_executable("node"), str(cli), *args], cwd=APP, env=env, check=True)


def target_deployment(cfg, state, registry_path=None):
    path = registry_path or APP / "rayfin" / ".deployments.json"
    registry = json.loads(path.read_text(encoding="utf-8-sig"))
    record = registry["deployments"].get(registry.get("active"), {})
    if (record.get("fabricTenantId") != cfg["tenant_id"]
            or record.get("fabricWorkspaceId") != state["workspace_id"]):
        raise RuntimeError("Rayfin's active deployment does not match the approved tenant/workspace.")
    return record


def update_redirects(token, app, hosting_url):
    origin = hosting_url.rstrip("/")
    parsed = urlparse(origin)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".webapp.fabricapps.net"):
        raise RuntimeError("Unexpected Fabric App hosting origin; refusing to register a redirect.")
    current = graph_call(token, "GET", f"applications/{app['id']}", params={"$select": "spa"})
    uris = set(current.get("spa", {}).get("redirectUris", []))
    uris.update((origin, f"{origin}/blank.html"))
    graph_call(token, "PATCH", f"applications/{app['id']}", json={"spa": {"redirectUris": sorted(uris)}})
    return origin


def verify_host(origin):
    for route in ("/", "/blank.html", "/diagnostic"):
        response = requests.get(f"{origin}{route}", timeout=90)
        response.raise_for_status()
        if "<html" not in response.text.lower():
            raise RuntimeError(f"{route} is not the deployed application HTML.")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Read-only prerequisites; no remote or file changes.")
    args = parser.parse_args()
    cfg, state = load_config(), load_state()
    tenant, workspace = preflight(cfg, state)
    if args.check:
        print("Application prerequisites passed; deployment has NOT been performed.")
        return
    graph_token = token_for("https://graph.microsoft.com", tenant)
    app = ensure_spa(graph_token, cfg, state, tenant, workspace)
    write_bindings(app_bindings(cfg, state))
    preserve_deployments(
        APP / "rayfin" / ".deployments.json",
        registry_key(require_config(cfg, "workspace_name")), tenant, workspace,
    )
    target = ["up", "--tenant", tenant, "--workspace-id", workspace, "--yes"]
    rayfin([*target, "--exclude-services", "staticHosting"], cfg, state)
    # The first pass creates the backend without publishing a bundle with an unknown host.
    target_deployment(cfg, state)
    rayfin(target, cfg, state)
    deployed = target_deployment(cfg, state)
    origin = update_redirects(graph_token, app, deployed["hostingUrl"])
    verify_host(origin)
    state.update(application_id=deployed["fabricItemId"], application_url=origin,
                 application_tenant_id=tenant, application_workspace_id=workspace)
    save_state(state)
    print(f"Fabric App deployed: {origin}")
    print("Hosting and redirects verified. Browser sign-in and live data/agent journeys remain a separate verification gate.")


if __name__ == "__main__":
    main()
