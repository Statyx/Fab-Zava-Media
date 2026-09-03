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
import re
import subprocess
import sys
import time
from typing import Any, Dict, Optional

from fabric._shared.platform_env import AZ_NEEDS_SHELL

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


_NOT_FOUND_MARKERS = ("notfound", "could not be found", "was not found",
                      "does not exist", "resourcenotfound")


def az_json_probe(args) -> Any:
    """`az ... show` used as a question, not an assertion. Absent returns None.

    Every ensure_* function is "read, then create if missing", so the read must be able
    to say "missing". az_json cannot: `az group show` exits non-zero when the group does
    not exist, so the very first deploy of a Foundry project died on

        AzError: (ResourceGroupNotFound) Resource group 'rg-zava-media' could not be found.

    at step 2 of 5 - the step whose entire job was to create it. Observed live 2026-09-02.
    The sibling probes escaped because arm_get() already maps 404 to None; this one used
    the raw runner.

    Only absence is swallowed. A permission error, an expired login or a bad subscription
    still raises, because those mean "you cannot tell", not "it is not there" - and
    creating on top of that guess is how you get a duplicate resource in the wrong place.
    """
    try:
        return az_json(args)
    except AzError as exc:
        low = str(exc).lower()
        if any(m in low for m in _NOT_FOUND_MARKERS):
            return None
        raise


def get_ai_token() -> str:
    """Data-plane token for the Agents API and for A2A. Audience: https://ai.azure.com."""
    return _az(["account", "get-access-token", "--resource", "https://ai.azure.com",
                "--query", "accessToken", "-o", "tsv"])


#: A Foundry agent name, as the Agents data plane defines it: alphanumeric at both ends,
#: hyphens allowed only in the middle, 63 characters maximum.
FOUNDRY_AGENT_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def check_agent_name(name: str, setting: str) -> str:
    """Reject a Foundry agent name the service will reject, before anything is created.

    ⚠️ A Foundry agent name is NOT a Fabric item name. Fabric accepts underscores
    happily - `Zava_Media_Analyst` is a live Fabric data agent on this tenant - so a
    naming convention that works everywhere else in the repository silently does not
    apply here. Observed live 2026-09-02:

        HttpResponseError: (invalid_parameters) Must start and end with alphanumeric
        characters, can contain hyphens in the middle, and must not exceed 63 characters.

    Two details make that failure expensive, which is why this check exists at all:

    1. It arrives from `agents.create_version`, at step 2 of 7, AFTER step 1 has already
       uploaded the whole contract corpus to a fresh vector store. The run dies having
       created a billable orphan.
    2. The message never names the offending value or the field it came from, so it reads
       like a malformed request body rather than "your configured name is illegal".

    Raising here, before the client is even built, costs one regex and turns a confusing
    mid-run 400 into a sentence naming the setting to edit.

    Args:
        name: the candidate agent name.
        setting: dotted config path it came from, quoted back to the user so the fix is
            unambiguous (e.g. ``foundry.contracts_agent_name``).

    Returns:
        The name unchanged, so this can wrap a lookup inline.

    Raises:
        SystemExit: via :func:`die`, with the rule and the likely correction.
    """
    if FOUNDRY_AGENT_NAME_RE.match(name):
        return name
    suggestion = re.sub(r"[^A-Za-z0-9-]+", "-", name).strip("-") or "agent"
    die(f"'{name}' is not a legal Foundry agent name (from {setting} in config.yaml).\n"
        f"The rule: alphanumeric at both ends, hyphens allowed only in the middle, 63 "
        f"characters maximum. Underscores are rejected.\n"
        f"This is NOT the Fabric rule - Fabric item names accept underscores, which is "
        f"why the rest of this config can use them.\n"
        f"Try: {suggestion}")


def foundry_credential():
    """`DefaultAzureCredential` with a subprocess timeout that fits a real Windows box.

    The default `process_timeout` is 10 seconds. Measured on this machine, a cold
    `az account get-access-token` takes ~6 seconds - a 1.7x margin, on a step that runs
    right after the deploy chain has been hammering ARM. One live run died on

        AzureCliCredential: Failed to invoke the Azure CLI

    with `az` working perfectly from the same shell, and did not reproduce on the next
    attempt. That is the signature of the timeout, not proof of it: the mechanism is
    consistent with everything observed, and no other cause was found. Raising the limit
    removes the failure mode whether or not it was the cause, and costs nothing when the
    CLI is fast - the timeout is a ceiling, not a delay.

    Every other step in this half goes through `az rest` via :func:`_az`, which has no
    such limit. These two SDK-based scripts are the only callers exposed to it.
    """
    from azure.identity import DefaultAzureCredential
    return DefaultAzureCredential(process_timeout=120)


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

    The shape is documented, but two hostnames circulate for a Foundry account and the
    docs are not self-consistent, so this used to be a guess the caller was told to check
    by hand against the portal.

    It no longer has to be. The tenant publishes the answer: an AIServices account carries
    a `properties.endpoints` MAP, and the one that matters is keyed "AI Foundry API".
    Verified on a real account 2026-09-02:

        properties.endpoint                      -> https://<acct>.cognitiveservices.azure.com/
        properties.endpoints["AI Foundry API"]   -> https://<acct>.services.ai.azure.com/

    The scalar `properties.endpoint` is the legacy Cognitive Services host and is the wrong
    one - reading it is the mistake this function exists to prevent.

    Falls back to the documented shape when the account cannot be read (no `az` session,
    or an offline unit test), so callers still get a usable value.
    """
    read = _account_ai_host(account_name)
    host = read or f"https://{account_name}.services.ai.azure.com"
    return f"{host.rstrip('/')}/api/projects/{project_name}"


def _account_ai_host(account_name: str) -> Optional[str]:
    """The "AI Foundry API" entry from the account's endpoints map, or None."""
    try:
        accounts = az_json_probe(["cognitiveservices", "account", "list"]) or []
        match = next((a for a in accounts if (a.get("name") or "") == account_name), None)
        if not match:
            return None
        rg = (match.get("resourceGroup") or "").strip()
        if not rg:
            return None
        acct = az_json_probe(["cognitiveservices", "account", "show",
                              "-n", account_name, "-g", rg])
        endpoints = ((acct or {}).get("properties") or {}).get("endpoints") or {}
        return endpoints.get("AI Foundry API") or None
    except Exception:
        return None


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
