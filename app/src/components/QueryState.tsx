/**
 * Loading / error / empty wrapper for anything backed by a DAX query.
 *
 * Failures are rendered in place, with the message the model returned. The alternative —
 * swallowing the error and drawing zeros — produces a screen that is confidently wrong, which
 * in a demo is far more damaging than a visible gap.
 */
import type { ReactNode } from 'react';

interface Props {
  loading: boolean;
  error: string | null;
  empty?: boolean;
  onRetry?: () => void;
  children: ReactNode;
}

export function QueryState({ loading, error, empty, onRetry, children }: Props) {
  if (loading) {
    return (
      <div
        className="flex items-center gap-3 p-6 text-sm"
        style={{ color: 'var(--text-secondary)' }}
      >
        <span
          className="h-4 w-4 animate-spin rounded-full border-2 border-t-transparent"
          style={{ borderColor: 'var(--accent)', borderTopColor: 'transparent' }}
        />
        Chargement des données…
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="rounded-lg border p-4"
        style={{
          borderColor: 'var(--sev-critical)',
          background: 'var(--bg-card-solid)',
        }}
      >
        <p className="text-sm font-medium" style={{ color: 'var(--sev-critical)' }}>
          La requête a échoué
        </p>
        <pre
          className="mt-2 whitespace-pre-wrap break-all text-xs"
          style={{ color: 'var(--sev-critical)' }}
        >
          {error}
        </pre>
        {onRetry && (
          <button
            onClick={onRetry}
            className="mt-3 rounded border px-3 py-1 text-xs font-medium"
            style={{
              borderColor: 'var(--sev-critical)',
              background: 'var(--bg-card-solid)',
              color: 'var(--sev-critical)',
            }}
          >
            Réessayer
          </button>
        )}
      </div>
    );
  }

  if (empty) {
    return (
      <div className="p-6 text-sm" style={{ color: 'var(--text-secondary)' }}>
        Aucune donnée retournée.
      </div>
    );
  }

  return <>{children}</>;
}
