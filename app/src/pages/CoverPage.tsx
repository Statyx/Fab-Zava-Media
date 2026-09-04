import { KpiCard } from '@/components/KpiCard';
import { Icon } from '@/components/Icon';
import { QueryState } from '@/components/QueryState';
import { COVER_DAX, mapCover } from '@/data/queries';
import {
  badgeForFamily,
  focusForFamily,
  routeForFamily,
  SECONDARY_NAV,
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
          Zava Media · operations console
        </p>
        <h1
          className="mt-3 text-3xl font-bold tracking-tight"
          style={{ color: 'var(--text-primary)' }}
        >
          Every campaign, from plan to invoice.
        </h1>
        <p className="mt-3 text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          Delivery against plan by market and quarter, the terms of each master agreement, and
          what has been billed against what was actually spent.
        </p>
      </header>

      {/* Counts come from the model, not from the copy. A hardcoded "80 campaigns" keeps its
          value after the data changes, which is exactly the kind of quiet lie this app exists
          not to tell. */}
      <div className="mt-8">
        <QueryState loading={loading} error={error} onRetry={reload}>
          {data ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <KpiCard label="Campaigns" value={String(data.campaigns)} measure="Total Campaigns" />
              <KpiCard
                label="Advertisers"
                value={String(data.advertisers)}
                measure="Total Advertisers"
              />
              <KpiCard label="Markets" value={String(data.markets)} measure="Total Markets" />
              <KpiCard
                label="Media owners"
                value={String(data.mediaOwners)}
                measure="Total Media Owners"
              />
              <KpiCard
                label="Over-delivered"
                value={String(data.over)}
                measure="Over-delivered Campaigns"
                tone={data.over > 0 ? 'alert' : 'default'}
              />
              <KpiCard
                label="Under-delivered"
                value={String(data.under)}
                measure="Under-delivered Campaigns"
                tone={data.under > 0 ? 'alert' : 'default'}
              />
            </div>
          ) : null}
        </QueryState>
      </div>

      <h2 className="mt-10 text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
        Where to start
      </h2>
      <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
        Pick a question and it opens the section that answers it, on the panel that carries it.
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
                    Data + contract
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

      {/* Second-rank, and it looks it. Architecture is the question that lands after the demo,
          not the reason anyone opened the console — so it gets one muted line under the cards
          rather than a card of its own competing with the six real questions. */}
      <div className="mt-8 border-t pt-4" style={{ borderColor: 'var(--border)' }}>
        {SECONDARY_NAV.map((entry) => (
          <button
            key={entry.to}
            onClick={() => go(entry.to)}
            className="inline-flex items-center gap-1.5 text-xs transition hover:underline focus-visible:outline-2 focus-visible:outline-offset-2"
            style={{ color: 'var(--text-muted)' }}
          >
            <Icon d={entry.icon} className="h-3.5 w-3.5" />
            {entry.label}
            <span className="hidden sm:inline">— {entry.blurb}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
