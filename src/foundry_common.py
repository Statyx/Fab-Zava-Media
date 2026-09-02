"""
Shared helpers for the Foundry half of the Zava Media demo.

Everything here is ARM / data-plane REST over the Azure CLI token. We deliberately do
NOT wrap the ARM surface in an SDK: the Foundry control plane moved twice during this
brain's lifetime, and `az rest` fails loudly with the server's own error text instead of
failing quietly inside a model class.

Two hostnames are in play and the Microsoft docs are not self-consistent about them:

    project endpoint   https://{account}.services.ai.azure.com/api/projects/{project}
    A2A base path      {project endpoint}/agents/{agent}/endpoint/protocols/a2a

Read both from the portal on a new tenant rather than inferring one from the other.
Source: Azure-Brain/Foundry-Brain/agents/foundry-orchestration-agent/known_issues.md,
"Two hostnames, and the docs disagree" (unresolved contradiction in the source docs).

⚠️ The Agents data-plane api-version is the literal string "v1". A date-shaped value
returns 400 and reads like a broken route. ARM connections use a dated version instead —
the two are not the same and cannot be swapped.
"""

import json
import subprocess
import sys
import time
from typing import Any, Dict, Optional

from platform_env import AZ_NEEDS_SHELL

# ARM control plane (resource group, account, project, connections, deployments).
ARM_API_VERSION = "2025-04-01-preview"
# Agents data plane (agents, agent cards, protocol configuration). Literal "v1".
AGENTS_API_VERSION = "v1"

ARM_ROOT = "https://management.azure.com"


class AzError(RuntimeError):
    """An `az` invocation failed. Carries the server's own message, not a paraphrase."""


def _az(args, capture=True) -> str:
    try:
        out = subprocess.run(
            ["az", *args],
            shell=AZ_NEEDS_SHELL,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise AzError("Azure CLI not found on PATH. Install it, then `az login`.") from exc

    if out.returncode != 0:
        raise AzError((out.stderr or out.stdout or "").strip() or f"az {' '.join(args)} failed")
    return (out.stdout or "").strip()


def az_json(args) -> Any:
    """Run an `az` command and parse its JSON output. Empty output becomes None."""
    raw = _az([*args, "-o", "json"])
    if not raw:
        return None
    return json.loads(raw)


def get_ai_token() -> str:
    """Data-plane token for the Agents API and for A2A. Audience: https://ai.azure.com."""
    return _az(["account", "get-access-token", "--resource", "https://ai.azure.com",
                "--query", "accessToken", "-o", "tsv"])


def arm_request(method: str, url: str, body: Optional[Dict] = None,
                api_version: str = ARM_API_VERSION) -> Any:
    """
    One ARM call through `az rest`, which reuses the CLI's own credential.

    A connection is NOT validated at creation — a target pointing at a `.invalid` host
    was accepted with HTTP 200 on a live tenant. A 200 here says the record was written,
    never that the far end answers. Reachability is proven at invoke, not here.
    """
    sep = "&" if "?" in url else "?"
    full = f"{url}{sep}api-version={api_version}"
    args = ["rest", "--method", method, "--url", full]
    if body is not None:
        args += ["--body", json.dumps(body), "--headers", "Content-Type=application/json"]
    raw = _az(args)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def arm_get(url: str, api_version: str = ARM_API_VERSION) -> Optional[Any]:
    """GET that returns None on 404 instead of raising — for find-or-create flows."""
    try:
        return arm_request("GET", url, api_version=api_version)
    except AzError as exc:
        msg = str(exc)
        if "ResourceNotFound" in msg or "NotFound" in msg or "(404)" in msg or "404" in msg:
            return None
        raise


def account_scope(subscription_id: str, resource_group: str, account_name: str) -> str:
    return (f"{ARM_ROOT}/subscriptions/{subscription_id}"
            f"/resourceGroups/{resource_group}"
            f"/providers/Microsoft.CognitiveServices/accounts/{account_name}")


def project_scope(subscription_id: str, resource_group: str,
                  account_name: str, project_name: str) -> str:
    return f"{account_scope(subscription_id, resource_group, account_name)}/projects/{project_name}"


def project_endpoint(account_name: str, project_name: str) -> str:
    """
    The data-plane base URL every Agents call hangs off.

    Prefer the value the portal shows on *Project details*; this is the documented shape
    and is what the deploy writes to state when the portal has not been consulted.
    """
    return f"https://{account_name}.services.ai.azure.com/api/projects/{project_name}"


def a2a_base_path(endpoint: str, agent_name: str) -> str:
    """
    The connection target for an A2A subordinate.

    ⚠️ This is the BASE path. Never append an agent card path: Foundry resolves the card
    itself and negotiates the protocol version. Setting `agent_card_path` is actively
    harmful — tenant-observed.
    """
    return f"{endpoint}/agents/{agent_name}/endpoint/protocols/a2a"


def agents_request(method: str, endpoint: str, path: str,
                   body: Optional[Dict] = None, token: Optional[str] = None) -> Any:
    """
    One call against the Agents data plane, with the literal api-version "v1".

    Uses http.client rather than requests: the same reason as the OneLake path in
    helpers.py — requests/urllib3 has hung against these hosts.
    """
    import http.client
    from urllib.parse import urlparse

    token = token or get_ai_token()
    url = f"{endpoint}{path}"
    sep = "&" if "?" in url else "?"
    url = f"{url}{sep}api-version={AGENTS_API_VERSION}"

    parsed = urlparse(url)
    conn = http.client.HTTPSConnection(parsed.netloc, timeout=120)
    target = parsed.path + ("?" + parsed.query if parsed.query else "")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    payload = None
    if body is not None:
        payload = json.dumps(body)
        headers["Content-Type"] = "application/json"
    try:
        conn.request(method, target, body=payload, headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
        status = resp.status
    finally:
        conn.close()

    if status == 404:
        return None
    if status >= 400:
        raise AzError(f"{method} {path} -> HTTP {status}: {raw[:600]}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def wait_for(predicate, what: str, attempts: int = 30, delay: int = 10):
    """
    Poll until `predicate()` returns something truthy.

    Foundry account and project creation are eventually consistent: the ARM PUT returns
    before the data plane will answer. Creating an agent immediately afterwards fails in
    a way that reads like a permissions problem.
    """
    for i in range(attempts):
        try:
            result = predicate()
            if result:
                return result
        except Exception:  # noqa: BLE001 - transient during provisioning, by design
            pass
        if i == 0:
            print(f"    waiting for {what} ...", end="", flush=True)
        else:
            print(".", end="", flush=True)
        time.sleep(delay)
    print()
    raise AzError(f"Timed out waiting for {what} after {attempts * delay}s")


def require(cfg: Dict[str, Any], *path: str) -> Any:
    """Fetch a nested config key, failing with the full dotted path rather than a KeyError."""
    node: Any = cfg
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise SystemExit(f"ERROR: config.yaml is missing '{'.'.join(path)}'")
        node = node[key]
    if node is None or (isinstance(node, str) and (not node.strip() or node.startswith("<"))):
        raise SystemExit(f"ERROR: config.yaml '{'.'.join(path)}' is still a placeholder")
    return node


def banner(title: str):
    print("=" * 66)
    print(title)
    print("=" * 66)


def die(msg: str):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)
