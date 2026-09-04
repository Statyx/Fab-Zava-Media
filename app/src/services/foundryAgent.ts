/**
 * The Foundry supervisor — the only console in this demo that can put a figure and a clause
 * side by side.
 *
 * ── Why a second service at all ─────────────────────────────────────────────────────────
 * `dataAgent.ts` reaches the semantic model, the ontology and the Eventhouse. It cannot reach
 * the contract corpus, and it says so out loud when asked: *"I cannot see any delivery clauses
 * or client entitlements in this dataset, so whether anything is owed must come from the signed
 * master agreements."* That is a correct answer to a question the app should never have routed
 * there — and it was routing five of them there, on the entry screen, including the first card.
 *
 * The corpus sits behind an A2A subordinate that only the supervisor can call.
 * `foundry/deploy_foundry_agents.py` explains at length why it had to be a separate agent
 * rather than a `file_search` tool hung off the supervisor: with both on one agent the
 * connection-backed tool never fires, because `file_search` describes its own purpose to the
 * model while a connection tool surfaces only under a name that says nothing about what it
 * fronts. So the split is not an accident to be tidied away later — it is the fix.
 *
 * ── What this costs, and why it is worth it ─────────────────────────────────────────────
 * A supervisor turn is one HTTP request that stays open for the whole hop chain — measured at
 * 60-110 s against this project, against 40-60 s for a direct Fabric turn. There is no
 * intermediate event to poll: the response arrives complete or not at all. Progress is
 * therefore reported honestly as elapsed time rather than invented stages.
 *
 * In the demo that latency is mostly theoretical: every scripted question is served from the
 * frozen cache in five seconds. This path is what makes a *typed* question work, and what makes
 * the cache honest — the recorded answers are recorded from here, not written by hand.
 *
 * ── Shape ───────────────────────────────────────────────────────────────────────────────
 * Returns `AgentAnswer`, the same shape `askDataAgent` returns, so no UI code has to know
 * which console answered. The difference the room sees is in `toolsFired`.
 */
import { getToken, msalConfigured } from './msal';
import { FOUNDRY_SCOPES } from './msal';
import type { AgentAnswer, AgentCitation } from './dataAgent';

/**
 * Thrown only when the build lacks the endpoint or agent name needed to reach Foundry.
 *
 * Kept distinct from ordinary failures for the same reason `DataAgentNotConfiguredError` is:
 * a missing build variable is a deployment defect the rail should state plainly, not a
 * transient service error it should invite the user to retry.
 */
export class SupervisorNotConfiguredError extends Error {
  constructor(message = 'The Foundry supervisor is not configured for this build.') {
    super(message);
    this.name = 'SupervisorNotConfiguredError';
  }
}

const TIMEOUT_MS = 300_000;

const endpoint = import.meta.env.VITE_FOUNDRY_ENDPOINT;
const agentName = import.meta.env.VITE_FOUNDRY_SUPERVISOR_AGENT;

/** One turn at a time, for the same reason the Fabric client serialises: a demo has one screen. */
let askQueue: Promise<void> = Promise.resolve();

export function supervisorConfigured(): boolean {
  return Boolean(endpoint && agentName && msalConfigured);
}

function responsesUrl(): string {
  if (!endpoint || !agentName) throw new SupervisorNotConfiguredError();
  return `${endpoint.replace(/\/+$/, '')}/openai/v1/responses`;
}

/**
 * Pull the prose out of the response.
 *
 * `output` is a heterogeneous list — tool listings, A2A calls, their outputs, and the messages.
 * Anything that is not a message is skipped rather than stringified: a run's tool payloads
 * contain the contract text verbatim, and folding them into the answer would put a raw corpus
 * dump on a wall screen.
 *
 * The list can hold **several** messages, and joining them was a real defect: the recorded
 * answer to the unbilled-window question came back with two ninety-word paragraphs and two
 * `### SOURCE` blocks, against a prompt that asks for one of each. The supervisor had drafted a
 * reply, called the contracts agent again, and rewritten it — both drafts were in the list, and
 * both were being shown.
 *
 * So the answer is the last message carrying text, not the concatenation of all of them. That
 * message's own `content` parts *are* joined: those are one reply split into blocks, not
 * competing versions of it.
 */
export function readText(output: unknown): string {
  if (!Array.isArray(output)) return '';
  for (let i = output.length - 1; i >= 0; i -= 1) {
    const obj = output[i] as Record<string, unknown> | null;
    if (!obj || obj.type !== 'message') continue;
    const content = obj.content;
    if (!Array.isArray(content)) continue;
    const chunks: string[] = [];
    for (const part of content) {
      const text = (part as Record<string, unknown> | null)?.text;
      if (typeof text === 'string' && text.trim()) chunks.push(text);
    }
    const joined = chunks.join('\n').trim();
    if (joined) return joined;
  }
  return '';
}

/**
 * Read back which subordinates the supervisor genuinely called.
 *
 * Two traps here, both observed live rather than reasoned about:
 *
 *  - `mcp_list_tools` carries `server_label: "fabricdataagent"` on **every** run, including
 *    runs where the data agent was never called. It is the supervisor enumerating what it
 *    *could* reach. Counting it would report the Fabric agent as fired on a pure contracts
 *    question — precisely the false provenance this console exists to avoid.
 *  - each A2A hop appears twice, as `..._call` and `..._call_output`. `verify_foundry.py`
 *    counts both, which is why its output shows the contracts agent listed twice; that is fine
 *    for a diagnostic and wrong for the rail.
 *
 * So: only the request side of a call, by name, de-duplicated. An unrecognised name still
 * passes through verbatim — it is evidence, and a wrong friendly label is worse than an
 * unfamiliar true one.
 */
export function collectTools(output: unknown): string[] {
  if (!Array.isArray(output)) return [];
  const out: string[] = [];
  for (const item of output) {
    const obj = item as Record<string, unknown> | null;
    const type = typeof obj?.type === 'string' ? obj.type : '';
    if (!type.includes('call') || type.endsWith('_output')) continue;
    const name = obj?.name ?? obj?.server_label ?? obj?.connection_name;
    if (typeof name !== 'string' || !name.trim()) continue;
    if (!out.includes(name.trim())) out.push(name.trim());
  }
  return out;
}

/**
 * Citations, when the service exposes any.
 *
 * Measured against this project the message annotations come back empty: the supervisor is
 * instructed to carry its provenance in the `### SOURCE` block instead, which `splitAnswer`
 * files into its own panel. This still reads annotations because the service may start
 * populating them, and an empty array is a truthful answer in the meantime.
 */
function collectCitations(output: unknown): AgentCitation[] {
  if (!Array.isArray(output)) return [];
  const out: AgentCitation[] = [];
  for (const item of output) {
    const content = (item as Record<string, unknown> | null)?.content;
    if (!Array.isArray(content)) continue;
    for (const part of content) {
      const annotations = (part as Record<string, unknown> | null)?.annotations;
      if (!Array.isArray(annotations)) continue;
      for (const a of annotations as Record<string, unknown>[]) {
        const label = a?.text ?? a?.title ?? a?.label;
        if (typeof label !== 'string' || !label.trim()) continue;
        if (out.some((c) => c.label === label.trim())) continue;
        out.push({ label: label.trim(), detail: JSON.stringify(a) });
      }
    }
  }
  return out;
}

async function runOnce(
  prompt: string,
  onProgress?: (status: string) => void
): Promise<AgentAnswer> {
  if (!supervisorConfigured()) throw new SupervisorNotConfiguredError();

  const started = performance.now();
  onProgress?.('Supervisor: acquiring token');
  const token = await getToken(FOUNDRY_SCOPES, false);

  // The request holds open for the whole hop chain, so the only truthful progress available is
  // the clock. A ticker beats a frozen rail, and inventing stage names we cannot observe would
  // be the same dishonesty the provenance panel exists to prevent.
  onProgress?.('Supervisor: routing to the data agent and the contracts agent');
  const ticker = window.setInterval(() => {
    const seconds = Math.round((performance.now() - started) / 1000);
    onProgress?.(`Supervisor: still running (${seconds}s)`);
  }, 5000);

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const res = await fetch(responsesUrl(), {
      method: 'POST',
      signal: controller.signal,
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        input: prompt,
        // `type` is REQUIRED and its only legal value is the literal "agent_reference".
        // Omitting it fails with `Required property 'type' is missing` on
        // `agent_reference.type`, which reads like the SDK dropped a field rather than like
        // the payload is short one.
        agent_reference: { type: 'agent_reference', name: agentName },
      }),
    });

    const body = await res.text();
    if (!res.ok) throw new Error(`Foundry supervisor ${res.status}: ${body.slice(0, 300)}`);

    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(body) as Record<string, unknown>;
    } catch {
      throw new Error(`Foundry supervisor returned non-JSON: ${body.slice(0, 300)}`);
    }

    const status = String(payload.status ?? '');
    const text = readText(payload.output);
    // A run can complete with no prose — an incomplete run, or a content filter. Failing here
    // is better than handing the rail an empty answer that renders as a blank panel.
    if (status !== 'completed' || !text) {
      const detail = payload.error ?? payload.incomplete_details ?? status ?? 'no output';
      throw new Error(`Foundry supervisor did not answer: ${JSON.stringify(detail).slice(0, 300)}`);
    }

    return {
      text,
      citations: collectCitations(payload.output),
      toolsFired: collectTools(payload.output),
      durationMs: performance.now() - started,
    };
  } finally {
    window.clearInterval(ticker);
    window.clearTimeout(timeout);
  }
}

/**
 * Ask the supervisor. Serialised, so a second click queues rather than racing the first.
 *
 * `onProgress` receives short status strings so the rail can distinguish a long hop chain from
 * a frozen UI.
 */
export async function askSupervisor(
  prompt: string,
  onProgress?: (status: string) => void
): Promise<AgentAnswer> {
  const turn = askQueue.then(() => runOnce(prompt, onProgress));
  askQueue = turn.then(
    () => undefined,
    () => undefined
  );
  return turn;
}
