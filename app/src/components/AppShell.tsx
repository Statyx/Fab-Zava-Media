import { NavLink, useLocation } from 'react-router-dom';

import { Icon } from '@/components/Icon';
import { ModeBadge } from '@/components/ModeBadge';
import { ThemeToggle } from '@/components/ThemeToggle';
import { NAV, basePath } from '@/domain/nav';
import { useAuth } from '@/hooks/AuthContext';

/**
 * Application shell — house design system (glass + animated mesh + `data-theme`).
 *
 * The header stays dark in both themes: it is the one fixed anchor while the page below
 * repaints between light and dark. Everything else draws its colour from the CSS variables in
 * `main.css`, so a single attribute on <html> swaps the whole console.
 *
 * The shell owns the text size for everything inside it. No leaf component hardcodes a scale —
 * a component that sets its own cannot be reused at another one.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, signOut } = useAuth();
  const base = basePath(useLocation().pathname);

  return (
    <div
      className="flex min-h-screen flex-col text-base"
      style={{ background: 'var(--bg-secondary)', color: 'var(--text-primary)' }}
    >
      <header
        className="sticky top-0 z-30 border-b border-white/10"
        style={{
          background: 'var(--header-bg)',
          backdropFilter: 'blur(24px)',
          WebkitBackdropFilter: 'blur(24px)',
        }}
      >
        <div className="mx-auto flex h-[84px] max-w-[1400px] items-center gap-6 px-6">
          <NavLink to={base || '/'} className="flex shrink-0 items-center gap-3">
            <span
              className="flex h-10 w-10 items-center justify-center rounded-xl text-lg"
              style={{ background: 'var(--accent)', color: '#fff' }}
              aria-hidden
            >
              📺
            </span>
            <span className="leading-tight">
              <span className="block text-sm font-semibold text-white">Zava Media</span>
              <span className="block text-xs text-slate-400">
                De l’écart mesuré à la clause qui l’arbitre
              </span>
            </span>
          </NavLink>

          <nav className="ml-auto flex items-center gap-1">
            {NAV.map((entry) => (
              <NavLink
                key={entry.to}
                to={`${base}${entry.to}`}
                end
                className={({ isActive }) =>
                  [
                    'flex items-center gap-2 rounded-full px-3 py-2 text-sm font-medium transition',
                    'focus-visible:outline-2 focus-visible:outline-offset-2',
                    isActive ? 'text-white' : 'text-slate-400 hover:bg-white/5 hover:text-white',
                  ].join(' ')
                }
                style={({ isActive }) => (isActive ? { background: 'var(--accent)' } : undefined)}
              >
                <Icon d={entry.icon} className="h-4 w-4" />
                <span className="hidden lg:inline">{entry.label}</span>
              </NavLink>
            ))}
          </nav>

          <div className="flex shrink-0 items-center gap-3 border-l border-white/10 pl-4">
            <ModeBadge />
            <ThemeToggle />
            {user ? (
              <div className="hidden text-right leading-tight sm:block">
                <span className="block max-w-[10rem] truncate text-xs text-slate-300">
                  {user.name ?? user.email}
                </span>
                <button
                  onClick={() => void signOut()}
                  className="text-xs text-slate-500 transition-colors hover:text-slate-300 focus-visible:outline-2 focus-visible:outline-offset-2"
                >
                  Sign out
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <main className="relative min-h-0 flex-1 overflow-x-hidden">
        {/* Decoration only — `pointer-events: none`, and disabled under prefers-reduced-motion. */}
        <div className="mesh-bg" aria-hidden>
          <span className="mesh-blob" />
          <span className="mesh-blob" />
          <span className="mesh-blob" />
        </div>
        <div className="relative z-10 flex min-h-0 flex-1 flex-col">{children}</div>
      </main>
    </div>
  );
}
