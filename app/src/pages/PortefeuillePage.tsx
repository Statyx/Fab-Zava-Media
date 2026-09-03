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
 * the cover links to. `mesures` is the portfolio in figures; `relations` is the shape of the
 * estate, which is the only capability in this demo that a table cannot show.
 */
export function PortefeuillePage() {
  const { data, loading, error, reload } = useDax(PORTFOLIO_DAX, mapPortfolio);

  return (
    <>
      <Section
        id="mesures"
        title="Le portefeuille sur la période"
        provenance="Modèle sémantique SM_Zava_Media — Direct Lake"
      >
        <QueryState loading={loading} error={error} onRetry={reload}>
          {data ? (
            <div className="grid grid-cols-2 gap-3 @3xl:grid-cols-3 @6xl:grid-cols-5">
              <KpiCard
                label="Campagnes"
                value={fmtInt(data.campaigns)}
                measure="Total Campaigns"
                hint={`dont ${fmtInt(data.active)} actives`}
              />
              <KpiCard
                label="Budget planifié"
                value={fmtEur(data.plannedBudget)}
                measure="Planned Budget (EUR)"
              />
              <KpiCard
                label="Dépense nette"
                value={fmtEur(data.netSpend)}
                measure="Net Spend (EUR)"
                hint={`${fmtPct(data.consumption)} du budget`}
              />
              <KpiCard
                label="Sur-livrées"
                value={fmtInt(data.over)}
                measure="Over-delivered Campaigns"
                tone={data.over > 0 ? 'alert' : 'default'}
              />
              <KpiCard
                label="Sous-livrées"
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
          La remise consentie par une régie l’est à l’agence. Ce n’est pas un droit de
          l’annonceur, et aucune de ces mesures ne dit le contraire.
        </p>
      </Section>

      <Section
        id="relations"
        title="Comment le portefeuille est relié"
        provenance="Ontologie ONT_Zava_Media — 7 entités, 9 relations"
      >
        <p className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          L’annonceur est atteint <strong>par la marque</strong> : Annonceur → Marque → Campagne.
          Le raccourci direct campagne → annonceur n’existe pas dans le modèle, délibérément —
          c’est ce qui force un vrai parcours de graphe plutôt qu’une jointure déguisée.
        </p>

        <ul className="mt-3 grid gap-2 text-sm @3xl:grid-cols-2">
          {[
            'Annonceur → Marque → Campagne',
            'Campagne → Marché',
            'Campagne → Levier',
            'Campagne → Régie',
            'Facture → Campagne',
            'Facture → Régie',
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
          Le pacing en direct est branché sur l’entité Campagne, ce qui met le réservé, le
          facturé et le diffusé dans la même couche.
        </p>
      </Section>
    </>
  );
}
