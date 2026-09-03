import { KpiCard } from '@/components/KpiCard';
import { QueryState } from '@/components/QueryState';
import { COVER_DAX, mapCover } from '@/data/queries';
import {
  badgeForFamily,
  focusForFamily,
  routeForFamily,
  sectionLabelForFamily,
} from '@/domain/nav';
import { FAMILY_STYLE, OPENERS, starters } from '@/domain/openers';
import { useDax } from '@/hooks/useDax';
import { useGo } from '@/hooks/useGo';

/**
 * The cover.
 *
 * It sits outside the workspace chrome, and that is the whole point of it: a title page with a
 * nav rail and a chat panel beside it is just another screen. Passing through it and *then*
 * seeing the chrome appear is what makes the console feel entered rather than merely loaded.
 *
 * Every card is bound to a real question and a real destination. A card that only sets a mood
 * teaches the room nothing about what the app can be asked.
 */
export function CoverPage() {
  const go = useGo();
  const { data, loading, error, reload } = useDax(COVER_DAX, mapCover);

  const cards = starters(OPENERS);

  return (
    <div className="mx-auto max-w-[1400px] p-6 sm:p-10">
      <header className="max-w-3xl">
        <p
          className="text-xs font-semibold uppercase tracking-[0.18em]"
          style={{ color: 'var(--text-muted)' }}
        >
          Zava Media · console de pilotage
        </p>
        <h1
          className="mt-3 text-3xl font-bold tracking-tight"
          style={{ color: 'var(--text-primary)' }}
        >
          Le chiffre est ici. La clause ne l’est pas.
        </h1>
        <p className="mt-3 text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          Les écarts de livraison se mesurent dans le modèle sémantique. Ce à quoi ils donnent
          droit est écrit dans les contrats cadres, et nulle part ailleurs. Cette console pose
          les deux questions et montre laquelle a répondu.
        </p>
      </header>

      {/* Counts come from the model, not from the copy. A hardcoded "80 campagnes" keeps its
          value after the data changes, which is exactly the kind of quiet lie this app exists
          not to tell. */}
      <div className="mt-8">
        <QueryState loading={loading} error={error} onRetry={reload}>
          {data ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <KpiCard label="Campagnes" value={String(data.campaigns)} measure="Total Campaigns" />
              <KpiCard
                label="Annonceurs"
                value={String(data.advertisers)}
                measure="Total Advertisers"
              />
              <KpiCard label="Marchés" value={String(data.markets)} measure="Total Markets" />
              <KpiCard
                label="Régies"
                value={String(data.mediaOwners)}
                measure="Total Media Owners"
              />
              <KpiCard
                label="Sur-livrées"
                value={String(data.over)}
                measure="Over-delivered Campaigns"
                tone={data.over > 0 ? 'alert' : 'default'}
              />
              <KpiCard
                label="Sous-livrées"
                value={String(data.under)}
                measure="Under-delivered Campaigns"
                tone={data.under > 0 ? 'alert' : 'default'}
              />
            </div>
          ) : null}
        </QueryState>
      </div>

      <h2 className="mt-10 text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
        Par où commencer
      </h2>
      <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
        Chaque carte pose une vraie question et ouvre la section qui la porte. Le badge annonce
        ce qu’elle ira lire — ce qu’elle a réellement lu s’affiche sous la réponse.
      </p>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {cards.map((o) => {
          const style = FAMILY_STYLE[o.family];
          const badge = badgeForFamily(o.family);
          return (
            <button
              key={o.id}
              onClick={() =>
                go(`${routeForFamily(o.family)}?ask=${o.id}&focus=${focusForFamily(o.family)}`)
              }
              className="glass rounded-xl p-4 text-left transition hover:-translate-y-0.5 focus-visible:outline-2 focus-visible:outline-offset-2"
              style={{ borderTop: `3px solid ${style.accent}` }}
            >
              <div className="flex items-center gap-2">
                <span aria-hidden className="text-base">
                  {style.icon}
                </span>
                <span
                  className="text-[0.625rem] font-semibold uppercase tracking-wide"
                  style={{ color: 'var(--text-muted)' }}
                >
                  {style.area}
                </span>
                {o.kind === 'mixed' ? (
                  <span
                    className="ml-auto rounded-full px-2 py-0.5 text-[0.625rem] font-semibold"
                    style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}
                  >
                    Croisé
                  </span>
                ) : null}
              </div>

              <p
                className="mt-2 text-sm font-medium leading-snug"
                style={{ color: 'var(--text-primary)' }}
              >
                {o.label}
              </p>

              <div className="mt-3 flex items-center gap-2 text-[0.6875rem]">
                <span
                  className="rounded px-1.5 py-0.5 font-medium"
                  style={{ color: badge.tone, border: `1px solid ${badge.tone}` }}
                >
                  {badge.label}
                </span>
                <span style={{ color: 'var(--text-muted)' }}>
                  → {sectionLabelForFamily(o.family)}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
