import { KpiCard } from '@/components/KpiCard';
import { QueryState } from '@/components/QueryState';
import { Section } from '@/components/Section';
import {
  BILLING_DAX,
  BILLING_TOTALS_DAX,
  GRAIN_DAX,
  REBATE_DAX,
  mapBilling,
  mapBillingTotals,
  mapGrain,
  mapRebates,
} from '@/data/queries';
import { useAssistant } from '@/domain/assistant';
import { OPENERS } from '@/domain/openers';
import { fmtEur, fmtInt, fmtPct } from '@/lib/format';
import { useDax } from '@/hooks/useDax';

/**
 * Billing, and the one panel in the app that exists to prevent a misreading.
 *
 * Two true answers to "how much is unbilled" differ by a factor of three, because the billing
 * fact is at campaign x media owner while the question is asked about campaigns. Both counts
 * are correct at their own grain; neither is correct at the other's. Showing them side by
 * side, each labelled, is the only honest rendering — and it is the failure a demo of this
 * kind is most likely to walk into on stage.
 */
export function BillingPage() {
  const { ask } = useAssistant();
  const totals = useDax(BILLING_TOTALS_DAX, mapBillingTotals);
  const gaps = useDax(BILLING_DAX, mapBilling);
  const rebates = useDax(REBATE_DAX, mapRebates);
  const grain = useDax(GRAIN_DAX, mapGrain);

  return (
    <>
      <Section
        id="billed"
        title="Billed and disputed"
        provenance="Semantic model — billing fact, grain campaign × media owner"
      >
        <QueryState loading={totals.loading} error={totals.error} onRetry={totals.reload}>
          {totals.data ? (
            <div className="grid grid-cols-2 gap-3 @3xl:grid-cols-3 @6xl:grid-cols-5">
              <KpiCard
                label="Gross billed"
                value={fmtEur(totals.data.gross)}
                measure="Gross Billed (EUR)"
              />
              <KpiCard
                label="Net billed"
                value={fmtEur(totals.data.net)}
                measure="Net Billed (EUR)"
                hint={`${fmtInt(totals.data.invoices)} invoices`}
              />
              <KpiCard
                label="Net net"
                value={fmtEur(totals.data.netNet)}
                measure="Net Net Billed (EUR)"
                hint="after media owner rebate"
              />
              {/* A blank here is the model reporting no match, not a count of zero. Saying
                  "0" would put the same confidence on both, so the card names which it is. */}
              <KpiCard
                label="Disputed invoices"
                value={totals.data.disputed === null ? 'None' : fmtInt(totals.data.disputed)}
                measure="Disputed Invoices"
                tone={(totals.data.disputed ?? 0) > 0 ? 'alert' : 'default'}
                hint={
                  totals.data.disputed === null
                    ? 'no dispute in scope'
                    : fmtEur(totals.data.disputedAmount ?? 0)
                }
              />
              <KpiCard
                label="Billing vs spend gap"
                value={fmtEur(totals.data.gap)}
                measure="Billing vs Spend Gap (EUR)"
                tone={Math.abs(totals.data.gap) > 0 ? 'alert' : 'default'}
              />
            </div>
          ) : null}
        </QueryState>

        <QueryState loading={gaps.loading} error={gaps.error} onRetry={gaps.reload}>
          {(gaps.data ?? []).length > 0 ? (
            <table className="mt-4 w-full text-sm">
              <thead>
                <tr style={{ color: 'var(--text-muted)' }}>
                  <th className="pb-2 text-left text-xs font-medium">Advertiser · market</th>
                  <th className="pb-2 text-right text-xs font-medium">Net spend</th>
                  <th className="pb-2 text-right text-xs font-medium">Net billed</th>
                  <th className="pb-2 text-right text-xs font-medium">Gap</th>
                </tr>
              </thead>
              <tbody>
                {(gaps.data ?? []).slice(0, 8).map((g) => (
                  <tr
                    key={`${g.advertiser}-${g.market}`}
                    style={{ color: 'var(--text-secondary)' }}
                  >
                    <td className="py-1.5">
                      {g.advertiser}
                      <span className="ml-2 text-xs" style={{ color: 'var(--text-muted)' }}>
                        {g.market}
                      </span>
                    </td>
                    <td className="py-1.5 text-right tabular-nums">{fmtEur(g.netSpend)}</td>
                    <td className="py-1.5 text-right tabular-nums">{fmtEur(g.netBilled)}</td>
                    <td
                      className="py-1.5 text-right font-medium tabular-nums"
                      style={{ color: g.gap > 0 ? 'var(--sev-critical)' : 'var(--text-secondary)' }}
                    >
                      {fmtEur(g.gap)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </QueryState>
      </Section>

      <Section
        id="unbilled"
        title="What was never billed"
        provenance="Semantic model — shortfall between spend and billing, at campaign × media owner grain"
        action={
          <button
            onClick={() => {
              const o = OPENERS.find((x) => x.id === 'unbilled-window');
              if (o) ask(o);
            }}
            className="rounded-md px-2.5 py-1 text-xs font-medium"
            style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}
          >
            Ask the question
          </button>
        }
      >
        <QueryState loading={grain.loading} error={grain.error} onRetry={grain.reload}>
          {grain.data ? (
            <>
              {/* Two panels, two grains, each labelled. Never one number with a footnote —
                  the footnote is what gets skipped when the answer is read aloud. */}
              <div className="grid gap-3 @3xl:grid-cols-2">
                <div
                  className="rounded-lg p-4"
                  style={{
                    background: 'var(--bg-secondary)',
                    borderLeft: '3px solid var(--sev-high)',
                  }}
                >
                  <p
                    className="text-[0.625rem] font-semibold uppercase tracking-wide"
                    style={{ color: 'var(--text-muted)' }}
                  >
                    Campaign × media owner grain
                  </p>
                  <p
                    className="mt-1 text-2xl font-bold tabular-nums"
                    style={{ color: 'var(--text-primary)' }}
                  >
                    {fmtInt(grain.data.rows)}
                  </p>
                  <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                    billing lines short
                  </p>
                </div>

                <div
                  className="rounded-lg p-4"
                  style={{
                    background: 'var(--bg-secondary)',
                    borderLeft: '3px solid var(--sev-critical)',
                  }}
                >
                  <p
                    className="text-[0.625rem] font-semibold uppercase tracking-wide"
                    style={{ color: 'var(--text-muted)' }}
                  >
                    Campaign grain
                  </p>
                  <p
                    className="mt-1 text-2xl font-bold tabular-nums"
                    style={{ color: 'var(--text-primary)' }}
                  >
                    {fmtInt(grain.data.campaigns)}
                  </p>
                  <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                    campaigns affected · {fmtEur(grain.data.amount)}
                  </p>
                </div>
              </div>

              {grain.data.names.length > 0 ? (
                <p className="mt-2 text-xs" style={{ color: 'var(--text-secondary)' }}>
                  {grain.data.names.join(' · ')}
                </p>
              ) : null}

              <p className="mt-3 text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
                Both figures are correct. They do not answer the same question: a campaign booked
                with three media owners produces three lines. Asking "how many campaigns" and
                being handed a count of lines is a factor-of-three error that raises nothing on
                screen.
              </p>
              <p className="mt-2 text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                The claim window is set by the agreement, not by the billing data. The question
                above reads it from the signed contract for the account concerned.
              </p>
            </>
          ) : null}
        </QueryState>
      </Section>

      <Section
        id="rebates"
        title="Rebates granted by media owners"
        provenance="Semantic model — media owner → agency rebate"
      >
        <QueryState loading={rebates.loading} error={rebates.error} onRetry={rebates.reload}>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ color: 'var(--text-muted)' }}>
                <th className="pb-2 text-left text-xs font-medium">Media owner</th>
                <th className="pb-2 text-right text-xs font-medium">Gross billed</th>
                <th className="pb-2 text-right text-xs font-medium">Rebate</th>
                <th className="pb-2 text-right text-xs font-medium">% of gross</th>
              </tr>
            </thead>
            <tbody>
              {(rebates.data ?? []).map((r) => (
                <tr key={r.mediaOwner} style={{ color: 'var(--text-secondary)' }}>
                  <td className="py-1.5">{r.mediaOwner}</td>
                  <td className="py-1.5 text-right tabular-nums">{fmtEur(r.gross)}</td>
                  <td className="py-1.5 text-right tabular-nums">{fmtEur(r.rebate)}</td>
                  <td className="py-1.5 text-right tabular-nums">{fmtPct(r.rebatePct, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <p className="mt-3 text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            This rebate is granted by the media owner to the agency. It is not an advertiser
            entitlement, and nothing in this table may be presented as one.
          </p>
        </QueryState>
      </Section>
    </>
  );
}
