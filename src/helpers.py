#!/usr/bin/env python3
"""
Shared helpers for the Zava Media deployment scripts.
Authentication, async polling, config/state, Fabric items, Kusto (Eventhouse).

Reused from the proven Fab-Network-Operations pattern — keep the two in step.
"""

import base64
import json
import os
import re
import subprocess
import time
import yaml
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from platform_env import AZ_NEEDS_SHELL

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "config.yaml"
STATE_FILE = SCRIPT_DIR / "state.json"

# Tenant / capacity / workspace identifiers are NEVER hard-coded in this repo.
# Resolution order for each of them:  environment variable → config.yaml → error.
CONFIG_ENV_OVERRIDES = {
    "tenant_id":       "ZAVA_TENANT_ID",
    "capacity_id":     "ZAVA_CAPACITY_ID",
    "workspace_name":  "ZAVA_WORKSPACE_NAME",
    "az_subscription": "ZAVA_AZ_SUBSCRIPTION",
    "fabric_api_base": "ZAVA_FABRIC_API_BASE",
}
# Same idea for runtime item IDs: environment variable → state.json → error.
STATE_ENV_OVERRIDES = {
    "workspace_id":      "ZAVA_WORKSPACE_ID",
    "lakehouse_id":      "ZAVA_LAKEHOUSE_ID",
    "eventhouse_id":     "ZAVA_EVENTHOUSE_ID",
    "kql_database_id":   "ZAVA_KQL_DATABASE_ID",
    "ontology_id":       "ZAVA_ONTOLOGY_ID",
    "semantic_model_id": "ZAVA_SEMANTIC_MODEL_ID",
    "data_agent_id":     "ZAVA_DATA_AGENT_ID",
}

# "<YOUR_TENANT_ID>", "<filled by deploy_workspace.py>", … are templates, not values.
_PLACEHOLDER = re.compile(r"^\s*<.*>\s*$")


def _is_placeholder(value: Any) -> bool:
    return value is None or value == "" or bool(_PLACEHOLDER.match(str(value)))


def load_config() -> Dict[str, Any]:
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"{CONFIG_FILE} not found. Copy src/config.example.yaml to src/config.yaml "
            f"and fill in your own capacity_id / tenant_id (never commit it)."
        )
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    for key, env_var in CONFIG_ENV_OVERRIDES.items():
        env_value = os.getenv(env_var)
        if env_value:
            cfg[key] = env_value
    return cfg


def require_config(cfg: Dict[str, Any], key: str) -> Any:
    """Return cfg[key], or raise an explicit error naming the env var to set."""
    value = cfg.get(key)
    if _is_placeholder(value):
        env_var = CONFIG_ENV_OVERRIDES.get(key)
        hint = f" or export {env_var}" if env_var else ""
        raise RuntimeError(
            f"Missing '{key}': set it in src/config.yaml{hint}. "
            f"This repo ships no real tenant/capacity identifiers."
        )
    return value


def load_state() -> Dict[str, Any]:
    """Load deployment state (IDs created so far), with env-var overrides."""
    state: Dict[str, Any] = {}
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    for key, env_var in STATE_ENV_OVERRIDES.items():
        env_value = os.getenv(env_var)
        if env_value:
            state[key] = env_value
    return state


def require_state(state: Dict[str, Any], key: str) -> Any:
    """Return state[key], or raise an explicit error naming the env var to set."""
    value = state.get(key)
    if _is_placeholder(value):
        env_var = STATE_ENV_OVERRIDES.get(key)
        hint = f" or export {env_var}" if env_var else ""
        raise RuntimeError(
            f"Missing '{key}' in src/state.json{hint}. "
            f"Run the deploy step that produces it (see README deploy order)."
        )
    return value


def save_state(state: Dict[str, Any]):
    """Persist deployment state."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# On Windows `az` is a .cmd shim, which CreateProcess cannot launch directly — hence
# shell=True. On POSIX, shell=True with an argv list would run only "az" and drop every
# argument, so the shell must stay off there.
def get_fabric_token() -> str:
    """Get Fabric API access token via Azure CLI."""
    result = subprocess.check_output(
        ["az", "account", "get-access-token",
         "--resource", "https://api.fabric.microsoft.com",
         "--query", "accessToken", "-o", "tsv"],
        shell=AZ_NEEDS_SHELL
    )
    return result.decode().strip()


def get_storage_token() -> str:
    """Get a OneLake (storage) token — a different audience from the Fabric API one."""
    result = subprocess.check_output(
        ["az", "account", "get-access-token",
         "--resource", "https://storage.azure.com",
         "--query", "accessToken", "-o", "tsv"],
        shell=AZ_NEEDS_SHELL
    )
    return result.decode().strip()


def get_kusto_token(query_service_uri: str) -> str:
    """Get Kusto token, trying multiple scopes."""
    scopes = [
        query_service_uri,
        "https://kusto.kusto.windows.net",
        "https://help.kusto.windows.net",
        "https://api.fabric.microsoft.com",
    ]
    for scope in scopes:
        try:
            result = subprocess.check_output(
                ["az", "account", "get-access-token",
                 "--resource", scope,
                 "--query", "accessToken", "-o", "tsv"],
                shell=AZ_NEEDS_SHELL
            )
            token = result.decode().strip()
            if token:
                return token
        except subprocess.CalledProcessError:
            continue
    raise RuntimeError("Could not acquire Kusto token with any scope")


def fabric_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def poll_operation(token: str, api_base: str, operation_id: str,
                   max_wait: int = 120) -> Dict:
    """Poll an async Fabric operation until completion."""
    headers = fabric_headers(token)
    for _ in range(max_wait // 5):
        time.sleep(5)
        resp = requests.get(f"{api_base}/operations/{operation_id}",
                            headers=headers)
        resp.raise_for_status()
        op = resp.json()
        status = op.get("status", "")
        if status == "Succeeded":
            return op
        if status in ("Failed", "Cancelled"):
            raise RuntimeError(f"Operation {status}: {op.get('error', {})}")
    raise TimeoutError(f"Operation {operation_id} did not complete in {max_wait}s")


def create_fabric_item(token: str, api_base: str, workspace_id: str,
                       display_name: str, item_type: str,
                       description: str = "",
                       definition: Optional[Dict] = None) -> Dict:
    """Create a Fabric item and poll until complete."""
    headers = fabric_headers(token)
    body: Dict[str, Any] = {
        "displayName": display_name,
        "type": item_type,
    }
    if description:
        body["description"] = description
    if definition:
        body["definition"] = definition

    resp = requests.post(
        f"{api_base}/workspaces/{workspace_id}/items",
        headers=headers, json=body
    )

    if resp.status_code == 200:
        return resp.json()
    elif resp.status_code in (201, 202):
        op_id = resp.headers.get("x-ms-operation-id")
        if op_id:
            poll_operation(token, api_base, op_id)
            result = requests.get(
                f"{api_base}/operations/{op_id}/result",
                headers=headers
            )
            if result.status_code == 200:
                return result.json()
        return find_item(token, api_base, workspace_id, display_name, item_type)
    else:
        raise RuntimeError(f"Create {item_type} failed ({resp.status_code}): {resp.text}")


def find_item(token: str, api_base: str, workspace_id: str,
              display_name: str, item_type: str) -> Dict:
    """Find an item by name and type in a workspace.

    Lists all items (no ?type= filter — that endpoint can return 404 in some
    workspaces) and filters client-side by displayName + type.
    """
    headers = fabric_headers(token)
    resp = requests.get(
        f"{api_base}/workspaces/{workspace_id}/items",
        headers=headers
    )
    resp.raise_for_status()
    for item in resp.json().get("value", []):
        if item.get("displayName") == display_name and item.get("type") == item_type:
            return item
    raise RuntimeError(f"{item_type} '{display_name}' not found")


def b64encode_json(obj: Any) -> str:
    """Base64-encode a JSON object for Fabric definition parts."""
    return base64.b64encode(json.dumps(obj).encode("utf-8")).decode("ascii")


def kusto_mgmt(query_service_uri: str, kusto_token: str,
               db_name: str, command: str) -> Dict:
    """Execute a Kusto management command."""
    headers = {
        "Authorization": f"Bearer {kusto_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    body = {"db": db_name, "csl": command}
    resp = requests.post(
        f"{query_service_uri}/v1/rest/mgmt",
        headers=headers, json=body, timeout=60
    )
    resp.raise_for_status()
    return resp.json()


def kusto_streaming_ingest(query_service_uri: str, kusto_token: str,
                           db_name: str, table_name: str,
                           csv_payload: str) -> None:
    """Ingest CSV data via the Kusto streaming ingestion REST API.

    Uses POST /v1/rest/ingest/{db}/{table}?streamFormat=Csv
    which is more reliable than .ingest inline for larger volumes.
    """
    headers = {
        "Authorization": f"Bearer {kusto_token}",
        "Content-Type": "text/csv; charset=utf-8",
    }
    url = (f"{query_service_uri}/v1/rest/ingest/"
           f"{db_name}/{table_name}?streamFormat=Csv")
    resp = requests.post(url, headers=headers, data=csv_payload.encode("utf-8"),
                         timeout=60)
    resp.raise_for_status()


def print_step(step: int, total: int, msg: str):
    print(f"\n[{step}/{total}] {msg}")
    print("-" * 60)
