import { KpiCard } from '@/components/KpiCard';
import { QueryState } from '@/components/QueryState';
import { Section } from '@/components/Section';
import { PORTFOLIO_DAX, mapPortfolio } from '@/data/queries';
import { fmtEur, fmtInt, fmtPct } from '@/lib/format';
import { useDax } from '@/hooks/useDax';

/**
 * Where things stand, and where to start looking.
 *
 * Two panels, and they answer two different kinds of question — hence the two focus anchors
 * the cover links to. `measures` is the portfolio in figures; `relationships` is the shape of
 * the estate, which is the only capability in this demo that a table cannot show.
 */
export function PortfolioPage() {
  const { data, loading, error, reload } = useDax(PORTFOLIO_DAX, mapPortfolio);

  return (
    <>
      <Section
        id="measures"
        title="The portfolio over the period"
        provenance="SM_Zava_Media semantic model — Direct Lake"
      >
        <QueryState loading={loading} error={error} onRetry={reload}>
          {data ? (
            <div className="grid grid-cols-2 gap-3 @3xl:grid-cols-3 @6xl:grid-cols-5">
              <KpiCard
                label="Campaigns"
                value={fmtInt(data.campaigns)}
                measure="Total Campaigns"
                hint={`${fmtInt(data.active)} of them active`}
              />
              <KpiCard
                label="Planned budget"
                value={fmtEur(data.plannedBudget)}
                measure="Planned Budget (EUR)"
              />
              <KpiCard
                label="Net spend"
                value={fmtEur(data.netSpend)}
                measure="Net Spend (EUR)"
                hint={`${fmtPct(data.consumption)} of budget`}
              />
              <KpiCard
                label="Over-delivered"
                value={fmtInt(data.over)}
                measure="Over-delivered Campaigns"
                tone={data.over > 0 ? 'alert' : 'default'}
              />
              <KpiCard
                label="Under-delivered"
                value={fmtInt(data.under)}
                measure="Under-delivered Campaigns"
                tone={data.under > 0 ? 'alert' : 'default'}
              />
            </div>
          ) : null}
        </QueryState>

        {/* The rebate warning lives here rather than only on the billing screen, because this
            is the page an account director opens first and the misreading is expensive. */}
        <p className="mt-3 text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
          A rebate granted by a media owner is granted to the agency. It is not an advertiser
          entitlement, and none of these measures says otherwise.
        </p>
      </Section>

      <Section
        id="relationships"
        title="How the portfolio is connected"
        provenance="ONT_Zava_Media ontology — 7 entities, 9 relationships"
      >
        <p className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          The advertiser is reached <strong>through the brand</strong>: Advertiser → Brand →
          Campaign. The direct campaign → advertiser shortcut does not exist in the model, and
          that is deliberate — it is what forces a real graph traversal rather than a join in
          disguise.
        </p>

        <ul className="mt-3 grid gap-2 text-sm @3xl:grid-cols-2">
          {[
            'Advertiser → Brand → Campaign',
            'Campaign → Market',
            'Campaign → Channel',
            'Campaign → Media owner',
            'Invoice → Campaign',
            'Invoice → Media owner',
          ].map((path) => (
            <li
              key={path}
              className="rounded-lg px-3 py-2"
              style={{ background: 'var(--bg-secondary)', color: 'var(--text-secondary)' }}
            >
              {path}
            </li>
          ))}
        </ul>

        <p className="mt-3 text-xs" style={{ color: 'var(--text-muted)' }}>
          Live pacing is attached to the Campaign entity, which puts what was booked, what was
          billed and what actually ran in the same layer.
        </p>
      </Section>
    </>
  );
}
