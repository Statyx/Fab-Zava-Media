import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  askDataAgent,
  dataAgentConfigured,
  DataAgentNotConfiguredError,
} from '@/services/dataAgent';
import {
  askSupervisor,
  supervisorConfigured,
  SupervisorNotConfiguredError,
} from '@/services/foundryAgent';
import { AssistantContext, type AssistantApi, type Turn } from '@/domain/assistant';
import { frozenAnswer, REPLAY_MS } from '@/services/frozen';
import { deeper, followUps, starters, type Opener, type OpenerBackend } from '@/domain/openers';

/**
 * Owns the conversation for the whole console.
 *
 * Mounted once, above the routes, so moving between sections never costs the
 * user their thread.
 */
export function AssistantProvider({ children }: { children: React.ReactNode }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [asked, setAsked] = useState<string[]>([]);
  /**
   * The opener the answer on screen came from, so the rail can offer questions that dig into
   * *that* answer. Null after a typed question, which is correct: the console has no depth-2
   * questions for a sentence it did not write.
   */
  const [lastOpener, setLastOpener] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /** Id of the turn currently in flight, so the clock knows what to tick. */
  const runningId = useRef<string | null>(null);
  const seq = useRef(0);

  /**
   * A second-by-second clock, not a timestamp diff on render.
   *
   * Without it the elapsed time only advances when something else re-renders,
   * so a slow agent shows a frozen "0 s" for a minute and reads as a hang.
   */
  useEffect(() => {
    if (!busy) return;
    const t = window.setInterval(() => {
      setTurns((all) =>
        all.map((x) => (x.id === runningId.current ? { ...x, seconds: x.seconds + 1 } : x))
      );
    }, 1000);
    return () => window.clearInterval(t);
  }, [busy]);

  const run = useCallback(
    async (
      question: string,
      prompt: string,
      exercises: string | null,
      backend: OpenerBackend,
      openerId?: string
    ) => {
      if (busy) return;
      setBusy(true);
      setLastOpener(openerId ?? null);
      if (openerId) setAsked((a) => [...a, openerId]);

      const id = `turn-${++seq.current}`;
      runningId.current = id;
      setTurns((all) => [
        ...all,
        {
          id,
          question,
          prompt,
          exercises,
          status: 'running',
          progress: 'Sending the question…',
          seconds: 0,
          answer: null,
          error: null,
          replay: null,
        },
      ]);

      const patch = (p: Partial<Turn>) =>
        setTurns((all) => all.map((x) => (x.id === id ? { ...x, ...p } : x)));

      /**
       * The recording is checked before anything is sent.
       *
       * Deliberately in the provider and not in the service: the replay is a *presentation*
       * decision, not a data one, and burying it under `askDataAgent` would make a cached
       * answer indistinguishable from a live one at every call site — including in tests.
       */
      const recorded = frozenAnswer(prompt);
      if (recorded) {
        patch({ progress: 'Replaying a recorded answer…' });
        await new Promise((r) => setTimeout(r, REPLAY_MS));
        patch({
          status: 'done',
          progress: '',
          replay: { capturedAt: recorded.capturedAt, liveSeconds: recorded.seconds },
          answer: {
            text: recorded.text,
            citations: recorded.citations ?? [],
            toolsFired: recorded.toolsFired,
            durationMs: recorded.seconds * 1000,
            generatedQuery: recorded.generatedQuery,
          },
        });
        runningId.current = null;
        setBusy(false);
        return;
      }

      try {
        const askAgent = backend === 'foundry' ? askSupervisor : askDataAgent;
        const answer = await askAgent(prompt, (s) => patch({ progress: s }));
        patch({ status: 'done', answer, progress: '' });
      } catch (err) {
        patch({
          status: 'error',
          progress: '',
          error:
            err instanceof DataAgentNotConfiguredError
              ? 'The Data Agent is not configured in this build. The question above is the one that would be sent to it.'
              : err instanceof SupervisorNotConfiguredError
                ? 'The Foundry supervisor is not configured in this build, and this question needs the contracts. The question above is the one that would be sent to it.'
                : err instanceof Error
                  ? err.message
                  : String(err),
        });
      } finally {
        runningId.current = null;
        setBusy(false);
      }
    },
    [busy]
  );

  const ask = useCallback(
    (opener: Opener) =>
      void run(opener.label, opener.prompt, opener.exercises, opener.backend, opener.id),
    [run]
  );

  /**
   * Free text goes through unchanged, and goes to the supervisor.
   *
   * Unchanged, because dressing a typed question up with schema hints would make the app look
   * cleverer than it is and would silently change what the user asked.
   *
   * To the supervisor, because we cannot know what a typed question is about. The supervisor
   * holds the Fabric data agent as one of its tools, so it reaches everything the direct path
   * reaches *plus* the contracts — it is a superset, and the only route that cannot be wrong
   * about scope. It costs roughly forty seconds more on a question that turns out to be pure
   * data, which is the right trade for the alternative: a typed contract question answered by
   * an agent that then explains, on screen, that it cannot see contracts.
   */
  const askText = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      void run(trimmed, trimmed, null, 'foundry');
    },
    [run]
  );

  const value = useMemo<AssistantApi>(
    () => ({
      turns,
      busy,
      deeper: turns.length === 0 ? [] : deeper(lastOpener, asked),
      suggestions: turns.length === 0 ? starters() : followUps(asked),
      // Both consoles are needed: nine of the eighteen questions cannot be answered without
      // the contracts, including the first card on the entry screen.
      configured: dataAgentConfigured() && supervisorConfigured(),
      ask,
      askText,
    }),
    [turns, busy, asked, lastOpener, ask, askText]
  );

  return <AssistantContext.Provider value={value}>{children}</AssistantContext.Provider>;
}
