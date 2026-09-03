import { useState } from 'react';
import { statusText } from '@/domain/severity';
import { useAuth } from '@/hooks/AuthContext';

const msLogo = (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    width="16"
    height="16"
    viewBox="0 0 21 21"
    className="mr-2"
  >
    <rect x="1" y="1" width="9" height="9" fill="#f25022" />
    <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
    <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
    <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
  </svg>
);

export function AuthPage() {
  const { signIn, fabricAuthEnabled } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSignIn = async () => {
    setError(null);
    setIsLoading(true);

    try {
      await signIn();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Échec de la connexion.');
    } finally {
      setIsLoading(false);
    }
  };

  const buttonLabel = isLoading
    ? fabricAuthEnabled
      ? 'Ouverture de Fabric…'
      : 'Connexion…'
    : 'Se connecter avec Microsoft';

  return (
    <div className="auth-bg relative flex min-h-screen flex-col overflow-hidden">
      {/* Decoration only — never a signal, and it must not intercept the sign-in click. */}
      <div className="mesh-bg" aria-hidden>
        <span className="mesh-blob" />
        <span className="mesh-blob" />
        <span className="mesh-blob" />
      </div>

      <div className="relative z-10 flex flex-1 items-center justify-center p-4">
        <div className="w-full max-w-sm">
          <div className="glass rounded-3xl p-8">
            <div className="mb-8 text-center">
              <span
                className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl text-2xl"
                style={{ background: 'var(--accent)', color: '#fff' }}
                aria-hidden
              >
                📺
              </span>
              <h1 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>
                Zava Media
              </h1>
              <p className="mt-2 text-sm" style={{ color: 'var(--text-secondary)' }}>
                Livraison, contrats et facturation des campagnes.
              </p>
            </div>

            <button
              type="button"
              onClick={handleSignIn}
              disabled={isLoading}
              className="flex w-full items-center justify-center rounded-xl px-4 py-3 text-sm font-medium text-white transition-all hover:brightness-110 focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50 disabled:shadow-none"
              style={{
                background: 'linear-gradient(135deg, var(--accent), var(--accent-dark))',
                boxShadow: 'var(--shadow-md)',
              }}
            >
              {msLogo}
              {buttonLabel}
            </button>

            {error && (
              <p className={`mt-3 text-center text-sm ${statusText('fail')}`}>{error}</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
