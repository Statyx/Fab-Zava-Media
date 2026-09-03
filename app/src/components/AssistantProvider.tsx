import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  askDataAgent,
  dataAgentConfigured,
  DataAgentNotConfiguredError,
} from '@/services/dataAgent';
import { AssistantContext, type AssistantApi, type Turn } from '@/domain/assistant';
import { frozenAnswer, REPLAY_MS } from '@/services/frozen';
import { followUps, starters, type Opener } from '@/domain/openers';

/**
 * Owns the conversation for the whole console.
 *
 * Mounted once, above the routes, so moving between sections never costs the
 * user their thread.
 */
export function AssistantProvider({ children }: { children: React.ReactNode }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [asked, setAsked] = useState<string[]>([]);
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
    async (question: string, prompt: string, exercises: string | null, openerId?: string) => {
      if (busy) return;
      setBusy(true);
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
          progress: 'Envoi de la question…',
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
        patch({ progress: 'Rejeu d’une réponse enregistrée…' });
        await new Promise((r) => setTimeout(r, REPLAY_MS));
        patch({
          status: 'done',
          progress: '',
          replay: { capturedAt: recorded.capturedAt, liveSeconds: recorded.seconds },
          answer: {
            text: recorded.text,
            citations: [],
            toolsFired: recorded.toolsFired,
            durationMs: recorded.seconds * 1000,
          },
        });
        runningId.current = null;
        setBusy(false);
        return;
      }

      try {
        const answer = await askDataAgent(prompt, (s) => patch({ progress: s }));
        patch({ status: 'done', answer, progress: '' });
      } catch (err) {
        patch({
          status: 'error',
          progress: '',
          error:
            err instanceof DataAgentNotConfiguredError
              ? 'The Data Agent is not configured in this build. The question above is the one that would be sent to it.'
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
    (opener: Opener) => void run(opener.label, opener.prompt, opener.exercises, opener.id),
    [run]
  );

  /**
   * Free text goes through unchanged.
   *
   * Dressing a typed question up with schema hints would make the app look
   * cleverer than it is and would silently change what the user asked.
   */
  const askText = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      void run(trimmed, trimmed, null);
    },
    [run]
  );

  const value = useMemo<AssistantApi>(
    () => ({
      turns,
      busy,
      suggestions: turns.length === 0 ? starters() : followUps(asked),
      configured: dataAgentConfigured(),
      ask,
      askText,
    }),
    [turns, busy, asked, ask, askText]
  );

  return <AssistantContext.Provider value={value}>{children}</AssistantContext.Provider>;
}
