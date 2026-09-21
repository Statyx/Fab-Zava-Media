import type { CSSProperties } from 'react';
import { Link, useLocation } from 'react-router-dom';

import { KpiCard } from '@/components/KpiCard';
import { Icon } from '@/components/Icon';
import { QueryState } from '@/components/QueryState';
import { COVER_DAX, mapCover } from '@/data/queries';
import {
  badgeForFamily,
  basePath,
  focusForFamily,
  IQ_NAV,
  NAV,
  routeForFamily,
  sectionEntryForFamily,
  SECONDARY_NAV,
} from '@/domain/nav';
import { OPENERS, starters } from '@/domain/openers';
import { useDax } from '@/hooks/useDax';
import { useGo } from '@/hooks/useGo';
import { fmtInt } from '@/lib/format';

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
  const base = basePath(useLocation().pathname);
  const { data, loading, error, reload } = useDax(COVER_DAX, mapCover);

  const cards = starters(OPENERS).sort((a, b) =>
    NAV.indexOf(sectionEntryForFamily(a.family)) - NAV.indexOf(sectionEntryForFamily(b.family)),
  );

  return (
    <div className="cover-page">
      <header className="cover-hero">
        <p className="glass cover-eyebrow">
          <span aria-hidden>✦</span>
          Zava Media · connected context
        </p>
        <h1 className="cover-title">
          Your media ecosystem.{' '}
          <span className="portal-accent">Connected.</span>
        </h1>
        <p className="cover-intro">
          Campaigns, delivery, contracts and billing — connected through a shared business
          context. Explore the figures, the relationships and the terms behind each account.
        </p>
      </header>

      <section className="cover-metrics" aria-label="Portfolio at a glance">
        <QueryState loading={loading} error={error} onRetry={reload}>
          {data ? (
            <div className="cover-metrics-grid">
              <KpiCard
                variant="cover"
                icon="🎯"
                label="Campaigns"
                value={fmtInt(data.campaigns)}
                measure="Total Campaigns"
              />
              <KpiCard
                variant="cover"
                icon="👥"
                label="Advertisers"
                value={fmtInt(data.advertisers)}
                measure="Total Advertisers"
              />
              <KpiCard
                variant="cover"
                icon="🌍"
                label="Markets"
                value={fmtInt(data.markets)}
                measure="Total Markets"
              />
              <KpiCard
                variant="cover"
                icon="📡"
                label="Media owners"
                value={fmtInt(data.mediaOwners)}
                measure="Total Media Owners"
              />
              <KpiCard
                variant="cover"
                icon="↗"
                label="Over-delivered"
                value={fmtInt(data.over)}
                measure="Over-delivered Campaigns"
              />
              <KpiCard
                variant="cover"
                icon="↘"
                label="Under-delivered"
                value={fmtInt(data.under)}
                measure="Under-delivered Campaigns"
              />
            </div>
          ) : null}
        </QueryState>
      </section>

      <section className="cover-explore" aria-labelledby="cover-explore-title">
        <h2 id="cover-explore-title" className="cover-section-label">
          Explore — start with a business question
        </h2>

        <div className="cover-cards">
          {cards.map((o) => {
            const section = sectionEntryForFamily(o.family);
            const badge = badgeForFamily(o.family);
            const cardStyle: CSSProperties & { '--card-accent': string } = {
              '--card-accent': badge.tone,
            };
            return (
              <article
                key={o.id}
                className="glass portal-card cover-card"
                style={cardStyle}
              >
                <Link to={`${base}${section.to}`} aria-label={section.label} className="cover-card-heading">
                  <span aria-hidden className="cover-card-icon">
                    <Icon d={section.icon} className="h-5 w-5" />
                  </span>
                  <span>{section.label}</span>
                  <span className="cover-card-open">Open section <span aria-hidden>→</span></span>
                </Link>

                <button
                  type="button"
                  aria-label={o.label}
                  onClick={() =>
                    go(`${routeForFamily(o.family)}?ask=${o.id}&focus=${focusForFamily(o.family)}`)
                  }
                  className="cover-question-action"
                >
                  <span className="cover-card-question">{o.label}</span>

                  <span className="cover-card-footer">
                    <span className="cover-card-chips">
                      <span className="portal-chip">{badge.label}</span>
                      <span className="portal-chip">Ask this question</span>
                    </span>
                    <span aria-hidden className="portal-arrow">→</span>
                  </span>
                </button>
              </article>
            );
          })}
        </div>
        <p className="cover-caption">
          Open a section by its title, or ask the question below to start the conversation.
        </p>
      </section>

      <footer className="cover-platform">
        <button onClick={() => go(IQ_NAV.to)} className="glass cover-architecture cover-iq">
          <Icon d={IQ_NAV.icon} className="h-5 w-5 shrink-0" />
          <span>
            <span className="cover-architecture-title">{IQ_NAV.label}</span>
            <span className="cover-architecture-detail">{IQ_NAV.blurb}</span>
          </span>
          <span aria-hidden className="ml-auto">→</span>
        </button>
        {SECONDARY_NAV.map((entry) => (
          <button
            key={entry.to}
            onClick={() => go(entry.to)}
            className="glass cover-architecture"
          >
            <Icon d={entry.icon} className="h-5 w-5 shrink-0" />
            <span>
              <span className="cover-architecture-title">{entry.label}</span>
              <span className="cover-architecture-detail">
                The data, ontology and agents behind the experience
              </span>
            </span>
            <span aria-hidden className="ml-auto">→</span>
          </button>
        ))}
      </footer>
    </div>
  );
}
