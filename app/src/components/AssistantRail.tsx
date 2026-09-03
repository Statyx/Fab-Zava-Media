import { useEffect, useRef, useState } from 'react';

import { useAssistant } from '@/domain/assistant';
import type { Turn } from '@/domain/assistant';
import { Markdown } from '@/components/Markdown';
import { splitAnswer } from '@/services/answer';
import { frozenDate } from '@/services/frozen';
import { badgeForFamily } from '@/domain/nav';

/**
 * The assistant, pinned to a rail.
 *
 * ── Shape ───────────────────────────────────────────────────────────────────────────────
 * The user's question is a right-aligned accent bubble, the answer a left-aligned card, with
 * a step trace while the agent works and a free-text box so this is something you can talk to
 * rather than a menu of six buttons. Every colour resolves through the theme variables: an
 * early cut hardcoded `bg-white` and the `text-gray-*` ramp and left a white column down the
 * side of a dark console.
 *
 * It stays a rail — a fixed column at the edge, never half the screen. A half-and-half split
 * reads as "a chat app that happens to show a network", which inverts the product: the console
 * has to keep working on its own, with the assistant available at the side.
 *
 * ── What this rail refuses to do ────────────────────────────────────────────────────────
 * Everything below exists to stop the assistant looking more certain than it is. In order of
 * how badly each one would mislead a room:
 *
 *  1. **It shows what actually ran, not what was supposed to run.** Every suggestion declares
 *     up front what it expects to consult. After the answer, the rail shows what really fired
 *     — and lets it contradict the expectation. A console that only ever displays its own
 *     intentions is describing itself, not reporting.
 *  2. **An answer with no source says so, loudly.** Zero sources is not a rendering edge case,
 *     it is the single most important thing on screen: the model answered from itself.
 *  3. **It never animates work it cannot see.** The trace marks the hops the browser genuinely
 *     observes over HTTP. What happens inside the run — choosing a source, writing the query —
 *     is named, but greyed and labelled as unmeasured.
 *  4. **A replayed answer admits it.** A recording renders exactly like a live answer, which
 *     is precisely why the disclosure is mandatory rather than tasteful.
 *  5. **Provenance is kept but folded.** The agent returns its query and its tables; that is
 *     what makes the answer checkable. It sits one click away instead of drowning the prose.
 */

/**
 * Fabric's own vocabulary, translated for the operations floor.
 *
 * The names on the left are what the run steps return. The names on the right are what the
 * room needs: which body of data was consulted. Anything unrecognised passes through
 * unchanged — an unfamiliar true name is far better than a friendly wrong one, and a silent
 * fallback to "data" would erase exactly the evidence this badge exists to show.
 *
 * The first block was written against `itemReference.itemType`, which is what the runs were
 * expected to report. Six real captures report **none of it**: every one comes back as
 * orchestration step names instead. So the second block is the one that actually fires, and
 * without it the evidence line — the single most important line in this console — renders as
 * `generate.filename · analyze.database.execute · trace.analyze_ontology`. Both blocks stay:
 * the run shape is the agent's to change, and passing through is only safe for names nobody
 * has seen yet.
 */
export const SOURCE_LABEL: Record<string, string> = {
  Lakehouse: 'la table des livraisons et de la facturation',
  SemanticModel: 'le modèle sémantique',
  Warehouse: 'les tables de campagne',
  GraphQLApi: 'le graphe de relations',
  code_interpreter: 'un calcul',

  'analyze.database.execute': 'les données de campagne',
  'trace.analyze_ontology': 'le graphe de relations',
  'trace.analyze_semantic_model': 'le modèle sémantique',
};

/**
 * Steps that consulted nothing.
 *
 * These are real steps and they really fired — they just do not *read* anything. Naming a
 * file and translating a question into a query are the agent preparing to look; counting them
 * as sources would let an answer that never ran a query still claim it "read from" four
 * places. That is the one failure this badge exists to make impossible, so the filter runs
 * before the empty check and an answer with only scaffolding correctly falls through to the
 * "nothing was consulted" warning.
 */
export const NOT_A_SOURCE = new Set([
  'generate.filename',
  'analyze.database.nl2code',
  'analyze.database.fewshots.loading',
  'analyze.database.fewshots.matching',
]);

const sourceLabel = (name: string) => SOURCE_LABEL[name] ?? name;

/**
 * What the run really touched.
 *
 * Three states, and the middle one is the reason this component exists:
 *
 *  - **nothing fired** — an explicit warning. The answer may still be right, but it was not
 *    read out of the network, and anyone about to repeat it in a meeting needs to know that.
 *  - **one source** — stated plainly.
 *  - **more than one** — flagged as a synthesis, because combining sources is the thing this
 *    console does that a dashboard cannot.
 *
 * The count is over `new Set(...)`, never `length`: one source queried twice is still one
 * source, and calling that "synthesis" would inflate the claim on a technicality.
 */
function RouteBadges({ tools }: { tools: string[] }) {
  const unique = [...new Set(tools)].filter((t) => !NOT_A_SOURCE.has(t));

  if (unique.length === 0) {
    return (
      <p
        className="mt-2 flex items-start gap-1.5 rounded-lg border px-2 py-1.5 text-2xs"
        style={{
          borderColor: 'var(--sev-medium)',
          color: 'var(--sev-medium)',
          background: 'var(--bg-card-solid)',
        }}
      >
        <span aria-hidden="true">⚠</span>
        <span>Aucune source consultée — cette réponse n’a pas été lue dans les données.</span>
      </p>
    );
  }

  return (
    <div className="mt-2 flex flex-wrap items-center gap-1">
      <span className="text-2xs" style={{ color: 'var(--text-muted)' }}>
        Lu dans
      </span>
      {unique.map((t) => (
        <span
          key={t}
          className="rounded-full px-2 py-0.5 text-2xs"
          style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}
        >
          {sourceLabel(t)}
        </span>
      ))}
      {unique.length > 1 ? (
        <span className="text-2xs" style={{ color: 'var(--text-muted)' }}>
          · recoupé
        </span>
      ) : null}
    </div>
  );
}

/**
 * The phases the Data Agent actually reports, in order.
 *
 * Derived from the progress strings the service emits over real HTTP responses — not
 * invented. These three the browser genuinely observes.
 */
const STEPS = [
  { key: 'connect', label: 'Ouverture du fil' },
  { key: 'run', label: 'Exécution de la question' },
  { key: 'read', label: 'Rédaction de la réponse' },
] as const;

function phaseOf(progress: string): number {
  const p = progress.toLowerCase();
  if (p.includes('reading answer')) return 2;
  if (p.includes('creating thread') || p.includes('sending question')) return 0;
  // Anything else the poll loop reports means the run is under way.
  return 1;
}

function Trace({ progress }: { progress: string }) {
  const active = phaseOf(progress);
  return (
    <ol className="mt-3 space-y-1.5">
      {STEPS.map((s, i) => {
        const done = i < active;
        const now = i === active;
        return (
          <li key={s.key} className="flex items-center gap-2 text-xs">
            <span
              aria-hidden="true"
              className={`h-1.5 w-1.5 shrink-0 rounded-full ${now ? 'animate-pulse' : ''}`}
              style={{ background: done || now ? 'var(--accent)' : 'var(--border)' }}
            />
            <span style={{ color: now ? 'var(--text-secondary)' : 'var(--text-muted)' }}>
              {s.label}
            </span>
          </li>
        );
      })}

      {/*
        The fourth line is not a step, and it is styled so nobody can mistake it for one.

        Choosing a source and writing the query is the most interesting thing that happens in
        the whole exchange, and the browser sees none of it: the poll loop only ever reports
        that the run is still going. Naming it with an accent dot would be inventing
        instrumentation. Naming it in grey, marked as unmeasured, tells the truth and still
        answers the question the room is silently asking during a 90-second wait.
      */}
      <li className="flex items-start gap-2 text-xs">
        <span
          aria-hidden="true"
          className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
          style={{ background: 'var(--border)' }}
        />
        <span style={{ color: 'var(--text-muted)' }}>
          Choix d’une source et écriture de la requête
          <span className="block text-2xs italic">not measured here</span>
        </span>
      </li>
    </ol>
  );
}

function UserBubble({ turn }: { turn: Turn }) {
  return (
    <div className="flex flex-col items-end gap-1">
      <div
        className="max-w-[90%] rounded-2xl rounded-br-sm px-3 py-2 text-sm"
        style={{ background: 'var(--accent)', color: '#fff' }}
      >
        {turn.question}
      </div>
      {turn.exercises ? (
        <span className="text-2xs" style={{ color: 'var(--text-muted)' }}>
          should read {turn.exercises}
        </span>
      ) : null}
    </div>
  );
}

function AnswerBubble({ turn }: { turn: Turn }) {
  const a = turn.answer;
  if (!a) return null;
  const { body, source } = splitAnswer(a.text);

  return (
    <article
      className="max-w-[95%] rounded-2xl rounded-bl-sm border px-3 py-2.5"
      style={{ background: 'var(--bg-secondary)', borderColor: 'var(--border)' }}
    >
      <div className="text-sm" style={{ color: 'var(--text-secondary)' }}>
        <Markdown text={body} />
      </div>

      <RouteBadges tools={a.toolsFired} />

      {turn.replay ? (
        <p className="mt-2 text-2xs" style={{ color: 'var(--text-muted)' }}>
          Recorded {frozenDate(turn.replay.capturedAt)} — the live run took{' '}
          {turn.replay.liveSeconds}s
        </p>
      ) : null}

      {a.citations.length > 0 ? (
        <ul className="mt-2 space-y-0.5 border-t pt-2" style={{ borderColor: 'var(--border)' }}>
          {a.citations.map((c, i) => (
            <li key={i} className="text-xs" style={{ color: 'var(--text-muted)' }}>
              {c.label}
              {c.detail ? ` — ${c.detail}` : ''}
            </li>
          ))}
        </ul>
      ) : null}

      {/*
        Everything an engineer would ask for, one click away.

        The provenance block, the prompt that was sent and the query that was generated are
        what make the answer checkable rather than merely fluent — but printed inline they
        bury the sentence the operator actually needs. Folded, they cost one click and are
        still there when someone in the room says "prove it".
      */}
      <div className="mt-2 flex items-start justify-between gap-2">
        <details className="min-w-0 flex-1">
          <summary className="cursor-pointer text-2xs" style={{ color: 'var(--text-muted)' }}>
            D’où vient cette réponse
          </summary>

          {source ? (
            <div className="mt-1 text-2xs" style={{ color: 'var(--text-muted)' }}>
              <Markdown text={source} />
            </div>
          ) : null}

          <p
            className="mt-1.5 font-mono text-2xs leading-relaxed"
            style={{ color: 'var(--text-muted)' }}
          >
            {turn.prompt}
          </p>

          {a.generatedQuery ? (
            <pre
              className="mt-1.5 overflow-x-auto rounded p-2 font-mono text-2xs"
              style={{ background: 'var(--bg-card-solid)', color: 'var(--text-secondary)' }}
            >
              {a.generatedQuery}
            </pre>
          ) : null}
        </details>
        <span className="shrink-0 text-2xs" style={{ color: 'var(--text-muted)' }}>
          {(a.durationMs / 1000).toFixed(1)} s
        </span>
      </div>
    </article>
  );
}

/**
 * Separate the sentence a human can act on from the payload only a developer wants.
 *
 * Service errors arrive as a readable clause followed by a JSON body. Printed whole, the
 * useful half is lost inside the noise and a raw `400 {"error":...}` ends up on a projector.
 * The split is conservative: if there is no obvious payload boundary, nothing is hidden.
 */
function splitFailure(error: string): { message: string; detail: string | null } {
  const at = error.search(/[{[]/);
  if (at <= 0) return { message: error, detail: null };
  const message = error.slice(0, at).trim().replace(/[:\-–—]\s*$/, '');
  const detail = error.slice(at).trim();
  return message ? { message, detail } : { message: error, detail: null };
}

function Failure({ turn }: { turn: Turn }) {
  const { message, detail } = splitFailure(turn.error ?? '');
  return (
    <article
      className="max-w-[95%] rounded-2xl rounded-bl-sm border px-3 py-2.5"
      style={{ borderColor: 'var(--sev-high)', background: 'var(--bg-secondary)' }}
    >
      <p className="text-xs font-medium" style={{ color: 'var(--sev-high)' }}>
        La question n’a pas abouti
      </p>
      <p className="mt-1 text-xs" style={{ color: 'var(--text-secondary)' }}>
        {message}
      </p>
      <p className="mt-1 text-2xs" style={{ color: 'var(--text-muted)' }}>
        Abandon après {turn.seconds} s
      </p>
      <details className="mt-2">
        <summary className="cursor-pointer text-2xs" style={{ color: 'var(--text-muted)' }}>
          Détail technique
        </summary>
        <p
          className="mt-1 font-mono text-2xs leading-relaxed"
          style={{ color: 'var(--text-muted)' }}
        >
          {turn.prompt}
        </p>
        {detail ? (
          <pre
            className="mt-1.5 overflow-x-auto rounded p-2 font-mono text-2xs"
            style={{ background: 'var(--bg-card-solid)', color: 'var(--text-muted)' }}
          >
            {detail}
          </pre>
        ) : null}
      </details>
    </article>
  );
}

function Welcome({ configured }: { configured: boolean }) {
  return (
    <div
      className="rounded-xl border p-3"
      style={{ borderColor: 'var(--border)', background: 'var(--bg-secondary)' }}
    >
      <p className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
        Posez une question sur les campagnes
      </p>
      <p className="mt-1 text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
        {configured
          ? 'Les réponses sont lues dans le modèle sémantique, le corpus contractuel et le graphe de relations. Chacune indique ce qu’elle a consulté, et la requête dont elle est issue.'
          : 'L’assistant n’est pas câblé dans ce build. Les questions sont affichées telles qu’elles seraient envoyées, pour que le câblage se vérifie sans inventer de réponse.'}
      </p>
    </div>
  );
}

export function AssistantRail() {
  const { turns, busy, suggestions, configured, ask, askText } = useAssistant();
  const [draft, setDraft] = useState('');
  const tail = useRef<HTMLDivElement>(null);

  // New turns scroll themselves into view; otherwise a long answer pushes the
  // next question below the fold and the rail looks like it stopped responding.
  useEffect(() => {
    tail.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [turns]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (busy || !draft.trim()) return;
    askText(draft);
    setDraft('');
  };

  return (
    <aside
      className="flex h-full min-h-0 flex-col border-l"
      style={{ background: 'var(--bg-card-solid)', borderColor: 'var(--border)' }}
    >
      <header
        className="flex items-center gap-2 border-b px-4 py-3"
        style={{ borderColor: 'var(--border)' }}
      >
        <span
          aria-hidden="true"
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ background: configured ? 'var(--sev-low)' : 'var(--text-muted)' }}
        />
        <div className="min-w-0">
          <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            Assistant Zava
          </h2>
          <p className="truncate text-xs" style={{ color: 'var(--text-muted)' }}>
            {configured
              ? 'Lit le modèle, les contrats et le graphe'
              : 'Non configuré'}
          </p>
        </div>
      </header>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {turns.length === 0 ? <Welcome configured={configured} /> : null}

        {turns.map((t) => (
          <div key={t.id} className="space-y-2">
            <UserBubble turn={t} />
            {t.status === 'running' ? (
              <div
                className="max-w-[95%] rounded-2xl rounded-bl-sm border px-3 py-2.5"
                style={{ borderColor: 'var(--border)' }}
              >
                <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  {t.progress || 'Working…'} · {t.seconds}s
                </p>
                <Trace progress={t.progress} />
              </div>
            ) : null}
            {t.status === 'done' ? <AnswerBubble turn={t} /> : null}
            {t.status === 'error' ? <Failure turn={t} /> : null}
          </div>
        ))}
        <div ref={tail} />
      </div>

      {/*
        Suggestions in two acts.

        Three before the first question, then whatever is left after each answer. An opening
        wall of eight options is a decision, not an invitation — and the list empties itself
        exactly when the room has learned what a good question looks like and can type one.
      */}
      {suggestions.length > 0 ? (
        <div className="border-t px-4 pt-3" style={{ borderColor: 'var(--border)' }}>
          <p className="mb-2 text-xs font-medium" style={{ color: 'var(--text-muted)' }}>
            {turns.length === 0 ? 'Pour commencer' : 'Aller plus loin'}
          </p>
          <div className="space-y-1.5">
            {suggestions.map((s) => {
              const badge = badgeForFamily(s.family);
              return (
                <button
                  key={s.id}
                  onClick={() => ask(s)}
                  disabled={busy}
                  className="w-full rounded-xl border px-3 py-2.5 text-left transition-opacity hover:opacity-80 focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-40"
                  style={{ borderColor: 'var(--border)', background: 'var(--bg-secondary)' }}
                >
                  <span
                    className="block text-xs leading-snug"
                    style={{ color: 'var(--text-primary)' }}
                  >
                    {s.label}
                  </span>
                  <span
                    className="mt-1.5 inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-2xs"
                    style={{ background: 'var(--accent-soft)', color: badge.tone }}
                  >
                    <svg
                      aria-hidden="true"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth={2}
                      className="h-3 w-3 shrink-0"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" d={badge.icon} />
                    </svg>
                    {badge.label}
                  </span>
                </button>
              );
            })}
          </div>
          {turns.length === 0 ? (
            <p className="mt-2 text-2xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
              Le badge annonce ce que la question ira lire. Ce qu’elle a réellement lu s’affiche
              sous la réponse.
            </p>
          ) : null}
        </div>
      ) : null}

      <form
        onSubmit={submit}
        className="flex items-center gap-2 border-t px-4 py-3"
        style={{ borderColor: 'var(--border)' }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={busy}
          placeholder={busy ? 'Réponse en cours…' : 'Poser une question…'}
          aria-label="Poser une question à l’assistant Zava"
          className="min-w-0 flex-1 rounded-lg border px-3 py-2 text-sm outline-none focus-visible:outline-2 focus-visible:outline-offset-1 disabled:opacity-50"
          style={{
            borderColor: 'var(--border)',
            background: 'var(--bg-secondary)',
            color: 'var(--text-primary)',
          }}
        />
        <button
          type="submit"
          disabled={busy || !draft.trim()}
          className="shrink-0 rounded-lg px-3 py-2 text-sm font-medium transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
          style={{ background: 'var(--accent)', color: '#fff' }}
        >
          Envoyer
        </button>
      </form>
    </aside>
  );
}
