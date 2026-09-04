#!/usr/bin/env python3
"""
Record real agent answers so the demo's clicks are instant.

Why this exists
---------------
A live answer costs 40-160 seconds against Fabric and 60-110 against the supervisor, because
the work happens on the data side: the agent picks a source, writes the query, Fabric runs it,
and only then is there prose. That is the right trade for a genuine question and the wrong one
for a click in front of a room, where a minute of spinner is a minute of dead air -- and the
moment an audience decides the console is slow rather than thorough.

So the questions the console itself suggests are answered from a recording, revealed after
`REPLAY_MS` (5s) with a disclosure carrying the capture date and the duration the agent really
took.

Two consoles, because one of them cannot answer half the questions
------------------------------------------------------------------
Nine of the eighteen questions have to read a master agreement, and the Fabric data agent
cannot see the contract corpus -- it says so itself, in prose, on screen. Those go to the
Foundry supervisor, which reaches the contracts through an A2A subordinate. Each question
carries its own `backend` in the generated list, so the routing here is the same routing the
app uses rather than a second opinion about it.

Two rules make the freezing acceptable, and both are load-bearing:

  1. **Nothing here is written by hand.** Every answer comes out of a live agent, with the
     sources that really fired, the citations it really returned and the time it really took.
     A hand-written answer would look exactly as sourced as a real one on screen -- same prose,
     same provenance block, same route badges -- while being a fabrication, and nobody in the
     room could tell. So an answer where no source fired is REFUSED rather than recorded: that
     is the app's own "unsourced answer" case, and freezing it would make it look deliberate.

  2. **The questions are derived, never retyped.** The list comes from
     `app/src/data/frozen-questions.generated.json`, which `app/scripts/freeze-questions.ts`
     writes from the TypeScript registry. Replay matches on the exact prompt sent, so a prompt
     retyped here would simply never hit -- silently, with no error, and the demo would go back
     to waiting a minute per click with nobody able to say why.

This mirrors what the browser clients do in `app/src/services/dataAgent.ts` and
`app/src/services/foundryAgent.ts`: same endpoints, same walk for tools and citations. It is a
separate implementation because it runs without a browser, and the pieces it shares are the API
shape rather than any code.

Why it lives in `foundry/` rather than `fabric/data_agent/`
-----------------------------------------------------------
It has to reach both consoles, and `foundry/` is the layer already allowed to know about
`fabric/_shared`. The reverse would invert that dependency. It also needs
`foundry_common.foundry_credential`, whose subprocess-timeout fix is documented there and must
not be copy-pasted into a second place to drift.

Partial runs are useful
-----------------------
The file is written after every answer, and a miss is fail-safe: anything not recorded goes to
the live agent exactly as before. A run that dies at question 12 leaves 11 usable recordings.

Usage:
  python -m foundry.capture_frozen_answers                 # record what is missing
  python -m foundry.capture_frozen_answers --force         # re-record everything
  python -m foundry.capture_frozen_answers --depth 1       # openers only
  python -m foundry.capture_frozen_answers --backend foundry
  python -m foundry.capture_frozen_answers --only pacing-live
"""
import argparse, json, re, sys, time
from fabric._shared.platform_env import bootstrap
bootstrap()

import requests
from fabric._shared.helpers import (load_state, require_state, get_fabric_token,
                                    fabric_headers, print_step)
from fabric._shared.paths import ROOT
from foundry.foundry_common import foundry_credential

API = "https://api.fabric.microsoft.com/v1"
API_VERSION = "2024-02-15-preview"
# The browser client sends `stage` on every call; without it the endpoints 404 with a bare
# EntityNotFound that says nothing about which of the three ids is being rejected.
STAGE = "production"
# The audience for the Foundry data plane. Not `cognitiveservices.azure.com`, which is the
# obvious guess and is rejected 401 even though the account is a CognitiveServices resource.
FOUNDRY_SCOPE = "https://ai.azure.com/.default"
DATA = ROOT / "app" / "src" / "data"
QUESTIONS = DATA / "frozen-questions.generated.json"
ANSWERS = DATA / "frozen-answers.generated.json"

# A run holds a lock on its thread, so each question gets a fresh thread rather than queueing
# behind the previous one. The browser reuses a sticky thread because a user asks one question
# at a time; a batch recorder does not have that luxury.
RUN_BUDGET_S = 300
TERMINAL = {"completed", "failed", "cancelled", "expired"}


def _url(agent_path: str, path: str) -> str:
    return f"{API}/{agent_path}/aiassistant/openai{path}?stage={STAGE}&api-version={API_VERSION}"


def _call(agent_path: str, path: str, token: str, method: str = "GET", body=None, params=None):
    url = _url(agent_path, path)
    if params:
        url += "&" + "&".join(f"{k}={v}" for k, v in params.items())
    r = requests.request(method, url, headers=fabric_headers(token), json=body, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:400]}")
    return r.json() if r.text else {}


def _walk(value, hit):
    """Depth-first walk over the payload, calling `hit` on every dict.

    The preview payload is not stable enough to pin one field, and the browser client walks it
    the same way for the same reason. Tolerant on the way in, literal on the way out.
    """
    if isinstance(value, list):
        for item in value:
            _walk(item, hit)
    elif isinstance(value, dict):
        hit(value)
        for nested in value.values():
            _walk(nested, hit)


def collect_tools(steps) -> list:
    """Which sources the run genuinely touched: referenced item types and invoked tools."""
    out = []

    def push(name):
        if isinstance(name, str) and name.strip() and name.strip() not in out:
            out.append(name.strip())

    def hit(obj):
        ref = obj.get("itemReference")
        if isinstance(ref, dict):
            push(ref.get("itemType"))
        for call in obj.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            fn = (call.get("function") or {}).get("name")
            push(fn if isinstance(fn, str) and fn.strip() else call.get("type"))

    _walk(steps, hit)
    return out


def collect_citations(*payloads) -> list:
    """Grounding Fabric exposed. Never invented: an empty list stays empty."""
    out = []

    def push(label, detail=None):
        if not isinstance(label, str) or not label.strip():
            return
        item = {"label": label.strip()}
        if detail is not None:
            item["detail"] = detail if isinstance(detail, str) else json.dumps(detail)
        if item not in out:
            out.append(item)

    def hit(obj):
        ref = obj.get("itemReference")
        if isinstance(ref, dict):
            push(ref.get("name") or ref.get("displayName") or ref.get("itemId"),
                 {"itemId": ref.get("itemId"), "itemType": ref.get("itemType"),
                  "workspaceId": ref.get("workspaceId")})
        for a in obj.get("annotations") or []:
            if isinstance(a, dict):
                push(a.get("text") or a.get("title") or a.get("label")
                     or (a.get("file_citation") or {}).get("file_id"), a)

    for p in payloads:
        _walk(p, hit)
    return out


def message_text(message) -> str:
    parts = []
    for block in (message or {}).get("content") or []:
        if isinstance(block, dict):
            text = block.get("text")
            if isinstance(text, dict):
                text = text.get("value")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def find_query(steps) -> str:
    """The generated query, when the run exposes one. Display only."""
    found = []

    def hit(obj):
        for key in ("query", "generatedQuery", "queryText", "kql", "dax", "sql"):
            v = obj.get(key)
            if isinstance(v, str) and v.strip() and len(v.strip()) > 12:
                found.append(v.strip())

    _walk(steps, hit)
    return found[0] if found else ""


def ask(agent_path: str, assistant_id: str, prompt: str, token: str):
    """One question on its own thread. Returns (text, tools, citations, query, seconds)."""
    t0 = time.time()
    thread = _call(agent_path, "/threads", token, "POST", {})
    thread_id = thread.get("id")
    if not thread_id:
        raise RuntimeError("Fabric created a thread without returning an id.")

    # A thread handed back with a run still on it is not usable, and the failure cascades.
    #
    # Observed: a dropped connection left a run active; the next `POST /threads` returned that
    # same thread rather than a fresh one, so every following question in the batch died on
    # "Can't add messages to <thread> while a run <run> is active" -- one blip took out the
    # rest of the run. Fabric names the offending run in the message, so cancel it and carry on
    # rather than reporting a transport hiccup as six broken questions.
    try:
        _call(agent_path, f"/threads/{thread_id}/messages", token, "POST",
              {"role": "user", "content": prompt})
    except RuntimeError as exc:
        stuck = re.search(r"while a run (\S+?) is active", str(exc))
        if not stuck:
            raise
        print(f"        clearing a run left active on the thread ({stuck.group(1)})")
        sys.stdout.flush()
        try:
            _call(agent_path, f"/threads/{thread_id}/runs/{stuck.group(1)}/cancel",
                  token, "POST", {})
        except Exception:  # noqa: BLE001 - already cancelled, or gone; either way, retry below
            pass
        for _ in range(20):
            time.sleep(3)
            state = _call(agent_path, f"/threads/{thread_id}/runs/{stuck.group(1)}",
                          token).get("status")
            if state in TERMINAL:
                break
        _call(agent_path, f"/threads/{thread_id}/messages", token, "POST",
              {"role": "user", "content": prompt})

    run = _call(agent_path, f"/threads/{thread_id}/runs", token, "POST",
                {"assistant_id": assistant_id})
    run_id = run.get("id")
    if not run_id:
        raise RuntimeError("Fabric started a run without returning an id.")

    status = run.get("status")
    try:
        while status not in TERMINAL:
            if time.time() - t0 > RUN_BUDGET_S:
                raise TimeoutError(f"run still {status} after {RUN_BUDGET_S}s")
            time.sleep(3)
            status = _call(agent_path, f"/threads/{thread_id}/runs/{run_id}", token).get("status")
    except BaseException:
        # Our poll gave up, or the connection dropped under it. Fabric's run did not stop
        # either way, and leaving it active is what locks the thread for everything after.
        try:
            _call(agent_path, f"/threads/{thread_id}/runs/{run_id}/cancel", token, "POST", {})
        except Exception:  # noqa: BLE001 - best effort; the original failure is what matters
            pass
        raise

    if status != "completed":
        raise RuntimeError(f"run ended {status}")

    messages = _call(agent_path, f"/threads/{thread_id}/messages", token,
                     params={"limit": 10, "order": "desc"})
    steps = _call(agent_path, f"/threads/{thread_id}/runs/{run_id}/steps", token,
                  params={"limit": 100})

    answer = next((m for m in messages.get("data") or []
                   if m.get("role") == "assistant" and m.get("run_id") == run_id), None)
    return (message_text(answer), collect_tools(steps),
            collect_citations(answer, steps), find_query(steps),
            round(time.time() - t0, 1))


def ask_supervisor(endpoint: str, agent_name: str, prompt: str, token: str):
    """One turn against the Foundry supervisor. Same return shape as `ask`.

    Mirrors `app/src/services/foundryAgent.ts`, including the two traps that make a naive read
    of `output` report sources that never fired:

      - `mcp_list_tools` carries `server_label: "fabricdataagent"` on EVERY run, including runs
        where the data agent was never called. It is the supervisor enumerating what it could
        reach, not what it used.
      - each A2A hop appears twice, as `..._call` and `..._call_output`.

    So only the request side of a call, by name, de-duplicated.
    """
    t0 = time.time()
    url = f"{endpoint.rstrip('/')}/openai/v1/responses"
    body = {
        "input": prompt,
        # `type` is REQUIRED and its only legal value is the literal "agent_reference".
        "agent_reference": {"type": "agent_reference", "name": agent_name},
    }
    r = requests.post(url, headers={"Authorization": f"Bearer {token}",
                                    "Content-Type": "application/json"},
                      json=body, timeout=RUN_BUDGET_S)
    if r.status_code >= 400:
        raise RuntimeError(f"supervisor -> {r.status_code}: {r.text[:400]}")
    payload = r.json()

    status = payload.get("status")
    if status != "completed":
        detail = payload.get("error") or payload.get("incomplete_details") or status
        raise RuntimeError(f"run ended {json.dumps(detail)[:220]}")

    output = payload.get("output") or []

    tools = []
    for item in output:
        if not isinstance(item, dict):
            continue
        kind = item.get("type") or ""
        if "call" not in kind or kind.endswith("_output"):
            continue
        name = item.get("name") or item.get("server_label") or item.get("connection_name")
        if isinstance(name, str) and name.strip() and name.strip() not in tools:
            tools.append(name.strip())

    # Several messages can come back: the supervisor drafts a reply, calls a subordinate again,
    # and rewrites it. Joining them shipped the draft *and* the final answer one after the other
    # -- two ninety-word paragraphs and two SOURCE blocks in a recording. The answer is the last
    # message carrying text; its own content blocks are joined, being one reply split in parts.
    final = None
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        parts = [b.get("text") for b in (item.get("content") or [])
                 if isinstance(b, dict) and isinstance(b.get("text"), str) and b["text"].strip()]
        if parts:
            final = (item, "\n".join(parts).strip())

    # Only that message is scanned for citations. The A2A tool payloads carry the contract text
    # verbatim, and walking them would file the whole corpus as "grounding".
    if final is None:
        return "", tools, [], "", round(time.time() - t0, 1)
    return (final[1], tools, collect_citations([final[0]]), "",
            round(time.time() - t0, 1))


def main() -> int:
    ap = argparse.ArgumentParser(description="Record live agent answers for replay.")
    ap.add_argument("--force", action="store_true", help="re-record questions already held")
    ap.add_argument("--only", help="limit to one opener id")
    ap.add_argument("--depth", type=int, default=2, help="1 = openers only, 2 = + follow-ups")
    ap.add_argument("--backend", choices=("fabric", "foundry"),
                    help="limit to one console")
    ap.add_argument("--limit", type=int, help="stop after N recordings")
    args = ap.parse_args()

    if not QUESTIONS.exists():
        print(f"!! {QUESTIONS.name} is missing.")
        print("   Generate it first, so the list stays derived rather than typed:")
        print("   cd app && npx tsx scripts/freeze-questions.ts")
        return 1

    all_entries = json.loads(QUESTIONS.read_text(encoding="utf-8")).get("entries", [])
    entries = [e for e in all_entries
               if e.get("depth", 1) <= args.depth
               and (not args.only or e.get("id") == args.only)
               and (not args.backend or e.get("backend") == args.backend)]

    payload = {"_comment": "Written by foundry/capture_frozen_answers.py, never by "
                           "hand. A missing recording is fail-safe: the question goes to the "
                           "live agent, costing latency and never correctness.",
               "capturedAt": None, "answers": {}}
    if ANSWERS.exists():
        existing = json.loads(ANSWERS.read_text(encoding="utf-8"))
        if existing.get("answers"):
            payload = existing
    payload.setdefault("answers", {})
    answers = payload["answers"]

    # Drop recordings whose question no longer exists.
    #
    # The file is keyed by the exact prompt sent, so a reworded question leaves its old answer
    # behind: never replayed, never noticed, and still read as a recording of the current demo.
    # One question here was rewritten because its measure was structurally blank, and the answer
    # explaining that it had no data would have sat in the file indefinitely.
    #
    # This prunes against the full question list, never the filtered `entries`: `--only` selects
    # what to record, not what is allowed to exist.
    live = {e["prompt"] for e in all_entries}
    stale = [p for p in answers if p not in live]
    for p in stale:
        print(f"   pruned a recording of a question that no longer exists: "
              f"{answers[p].get('id', '?')}")
        del answers[p]

    state = load_state()
    todo = [e for e in entries if args.force or e["prompt"] not in answers]
    if args.limit:
        todo = todo[:args.limit]

    wanted = {e.get("backend", "fabric") for e in todo}

    # Each console is opened only if something is actually going there. Minting a Foundry token
    # for a Fabric-only run would prompt an interactive sign-in nobody asked for.
    agent_path = assistant_id = fabric_token = None
    if "fabric" in wanted:
        workspace_id = require_state(state, "workspace_id")
        agent_id = require_state(state, "data_agent_id")
        agent_path = f"workspaces/{workspace_id}/dataAgents/{agent_id}"
        fabric_token = get_fabric_token()
        # POST, not GET: the endpoint mints an assistant handle for the agent rather than
        # listing existing ones, and `model` is required but ignored -- the agent's own model is
        # used. A GET here 404s with a bare EntityNotFound that reads like a wrong item id.
        assistant = _call(agent_path, "/assistants", fabric_token, "POST",
                          {"model": "irrelevant"})
        assistant_id = assistant.get("id")
        if not assistant_id:
            print("!! The data agent returned no assistant id. Is it published?")
            return 1

    endpoint = supervisor_name = foundry_token = None
    if "foundry" in wanted:
        endpoint = require_state(state, "foundry_endpoint")
        supervisor_name = require_state(state, "foundry_supervisor_agent")
        foundry_token = foundry_credential().get_token(FOUNDRY_SCOPE).token

    print("=" * 78)
    print(f"CAPTURE -- {len(todo)} question(s) to record (of {len(entries)} selected)")
    print("           fabric 40-160s, foundry 60-110s; the file is written after every answer")
    print("=" * 78)
    if not todo:
        print("\nNothing to do. Use --force to re-record.")
        return 0

    ok = refused = failed = 0
    for i, e in enumerate(todo, 1):
        backend = e.get("backend", "fabric")
        print(f"\n[{i}/{len(todo)}] d{e['depth']} {backend:<7} {e['id']:<24} {e['label'][:48]}")
        sys.stdout.flush()
        # One retry, and only for failures that are about the transport rather than the question.
        #
        # Two show up in practice: the supervisor invokes the data agent over an HttpClient with
        # a fixed 100-second timeout, shorter than a cold Fabric query sometimes takes -- the
        # same question that failed answered in 84s on the next attempt -- and the connection to
        # the Foundry endpoint occasionally drops mid-run. Neither says anything about the
        # prompt. Everything else is reported on the first failure: a question the agent cannot
        # answer does not become answerable by being asked twice.
        attempts = 0
        while True:
            attempts += 1
            try:
                if backend == "foundry":
                    text, tools, citations, query, secs = ask_supervisor(
                        endpoint, supervisor_name, e["prompt"], foundry_token)
                else:
                    text, tools, citations, query, secs = ask(
                        agent_path, assistant_id, e["prompt"], fabric_token)
                break
            except Exception as exc:  # noqa: BLE001 - several unrelated failure types land here
                blip = ("timeout", "canceled", "cancelled", "ssl", "connection reset",
                        "connection aborted", "max retries")
                transient = any(w in str(exc).lower() for w in blip)
                if transient and attempts == 1:
                    print(f"        transport blip ({type(exc).__name__}) - retrying once")
                    sys.stdout.flush()
                    continue
                print(f"        FAILED: {type(exc).__name__}: {str(exc)[:220]}")
                failed += 1
                text = None
                break
        if text is None:
            continue

        # No source fired means the model answered from its weights. That is the app's own
        # "unsourced answer" case; recording it would freeze an ungrounded answer into the
        # demo and make it look deliberate.
        if not tools:
            print("        REFUSED: no source fired - the answer is not grounded.")
            refused += 1
            continue
        if not text:
            print("        REFUSED: empty answer.")
            refused += 1
            continue

        record = {"id": e["id"], "depth": e["depth"], "backend": backend, "text": text,
                  "toolsFired": tools, "citations": citations, "seconds": secs,
                  "capturedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if query:
            record["generatedQuery"] = query
        answers[e["prompt"]] = record
        payload["capturedAt"] = record["capturedAt"]
        ANSWERS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
        ok += 1
        print(f"        OK {secs}s, {len(text)} chars, sources={tools}, "
              f"citations={len(citations)}")
        sys.stdout.flush()

    print("\n" + "-" * 78)
    print(f"   {ok} recorded, {refused} refused, {failed} failed, {len(answers)} in the file")
    print(f"   -> {ANSWERS}")
    if ok < len(todo):
        print("   The rest stay live: a missing recording costs latency, never correctness.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
