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
export function FacturationPage() {
  const { ask } = useAssistant();
  const totals = useDax(BILLING_TOTALS_DAX, mapBillingTotals);
  const gaps = useDax(BILLING_DAX, mapBilling);
  const rebates = useDax(REBATE_DAX, mapRebates);
  const grain = useDax(GRAIN_DAX, mapGrain);

  return (
    <>
      <Section
        id="facture"
        title="Facturé et contesté"
        provenance="Modèle sémantique — fait de facturation, grain campagne × régie"
      >
        <QueryState loading={totals.loading} error={totals.error} onRetry={totals.reload}>
          {totals.data ? (
            <div className="grid grid-cols-2 gap-3 @3xl:grid-cols-3 @6xl:grid-cols-5">
              <KpiCard
                label="Facturé brut"
                value={fmtEur(totals.data.gross)}
                measure="Gross Billed (EUR)"
              />
              <KpiCard
                label="Facturé net"
                value={fmtEur(totals.data.net)}
                measure="Net Billed (EUR)"
                hint={`${fmtInt(totals.data.invoices)} factures`}
              />
              <KpiCard
                label="Net net"
                value={fmtEur(totals.data.netNet)}
                measure="Net Net Billed (EUR)"
                hint="après remise régie"
              />
              <KpiCard
                label="Factures contestées"
                value={fmtInt(totals.data.disputed)}
                measure="Disputed Invoices"
                tone={totals.data.disputed > 0 ? 'alert' : 'default'}
                hint={fmtEur(totals.data.disputedAmount)}
              />
              <KpiCard
                label="Écart facturation / dépense"
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
                  <th className="pb-2 text-left text-xs font-medium">Annonceur · marché</th>
                  <th className="pb-2 text-right text-xs font-medium">Dépense nette</th>
                  <th className="pb-2 text-right text-xs font-medium">Facturé net</th>
                  <th className="pb-2 text-right text-xs font-medium">Écart</th>
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
        id="manquants"
        title="Ce qui n’a pas été facturé"
        provenance="Modèle sémantique — dépense sans facturation en regard"
        action={
          <button
            onClick={() => {
              const o = OPENERS.find((x) => x.id === 'unbilled-window');
              if (o) ask(o);
            }}
            className="rounded-md px-2.5 py-1 text-xs font-medium"
            style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}
          >
            Poser la question
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
                    Grain campagne × régie
                  </p>
                  <p
                    className="mt-1 text-2xl font-bold tabular-nums"
                    style={{ color: 'var(--text-primary)' }}
                  >
                    {fmtInt(grain.data.rows)}
                  </p>
                  <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                    lignes de facturation manquantes
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
                    Grain campagne
                  </p>
                  <p
                    className="mt-1 text-2xl font-bold tabular-nums"
                    style={{ color: 'var(--text-primary)' }}
                  >
                    {fmtInt(grain.data.campaigns)}
                  </p>
                  <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                    campagnes concernées · {fmtEur(grain.data.amount)}
                  </p>
                </div>
              </div>

              {grain.data.names.length > 0 ? (
                <p className="mt-2 text-xs" style={{ color: 'var(--text-secondary)' }}>
                  {grain.data.names.join(' · ')}
                </p>
              ) : null}

              <p className="mt-3 text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
                Les deux chiffres sont justes. Ils ne répondent pas à la même question : une
                campagne réservée chez trois régies produit trois lignes. Demander « combien de
                campagnes » et recevoir un compte de lignes, c’est se tromper d’un facteur trois
                sans qu’aucune erreur ne s’affiche.
              </p>
              <p className="mt-2 text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                La fenêtre de réclamation, elle, n’est pas dans le modèle : c’est une clause. La
                question croisée ci-dessus va la chercher là où elle est écrite.
              </p>
            </>
          ) : null}
        </QueryState>
      </Section>

      <Section
        id="remises"
        title="Remises consenties par les régies"
        provenance="Modèle sémantique — remise régie → agence"
      >
        <QueryState loading={rebates.loading} error={rebates.error} onRetry={rebates.reload}>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ color: 'var(--text-muted)' }}>
                <th className="pb-2 text-left text-xs font-medium">Régie</th>
                <th className="pb-2 text-right text-xs font-medium">Brut facturé</th>
                <th className="pb-2 text-right text-xs font-medium">Remise</th>
                <th className="pb-2 text-right text-xs font-medium">% du brut</th>
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
            Cette remise est accordée par la régie à l’agence. Elle n’est pas un droit de
            l’annonceur, et rien dans ce tableau ne peut être présenté comme tel.
          </p>
        </QueryState>
      </Section>
    </>
  );
}
