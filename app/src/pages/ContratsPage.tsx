import { Section } from '@/components/Section';
import { AGREEMENTS, REGIME_STYLE } from '@/data/contracts';
import { useAssistant } from '@/domain/assistant';

/**
 * The contracts, and deliberately not a single figure.
 *
 * This is the one section that produces no measure, and that emptiness is the argument: the
 * entitlement is not in the warehouse. Adding a KPI strip here to make the page look balanced
 * would undo the whole demonstration.
 *
 * The summaries below are captions, not answers. Clicking one asks the corpus, and what comes
 * back carries its own citation. The app must never let a caption pass for evidence.
 */
export function ContratsPage() {
  const { askText } = useAssistant();

  return (
    <>
      <Section
        id="regimes"
        title="Cinq contrats cadres, trois régimes"
        provenance="Corpus contractuel — recherche vectorielle, agent dédié"
      >
        <p className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          Trois écarts du même ordre de grandeur produisent trois issues opposées. Aucun chiffre
          ne le laisse deviner, et aucune clause seule ne dit sur quelle campagne elle
          s’applique. Les deux ensemble, oui.
        </p>

        <div className="mt-4 space-y-2">
          {AGREEMENTS.map((a) => {
            const style = REGIME_STYLE[a.regime];
            return (
              <button
                key={a.id}
                onClick={() =>
                  askText(
                    `Dans le contrat cadre de ${a.advertiser}, que prévoit exactement la clause ` +
                      `de livraison ? Cite l'article et dis, en une phrase, ce que l'agence doit ` +
                      `faire si l'écart dépasse la tolérance. N'utilise aucun chiffre de ` +
                      `livraison : cette question porte sur le texte seul.`,
                  )
                }
                className="block w-full rounded-lg p-3 text-left transition hover:bg-[var(--bg-secondary)] focus-visible:outline-2 focus-visible:outline-offset-2"
                style={{ borderLeft: `3px solid ${style.tone}` }}
              >
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
                    {a.advertiser}
                  </span>
                  <span
                    className="rounded px-1.5 py-0.5 text-[0.625rem] font-semibold"
                    style={{ color: style.tone }}
                  >
                    {style.label}
                  </span>
                  <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                    {a.id} · {a.article}
                  </span>
                </div>
                <p className="mt-1 text-sm leading-snug" style={{ color: 'var(--text-secondary)' }}>
                  {a.summary}
                </p>
              </button>
            );
          })}
        </div>
      </Section>

      <Section id="frontiere" title="Pourquoi cette page ne montre aucun chiffre">
        <p className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          Le modèle sémantique ne contient aucun terme contractuel : il ne peut pas dire si un
          client a droit à une compensation, à une régularisation ou à un audit. Il donne la
          mesure, puis s’arrête. Inversement, l’agent contractuel ne calcule rien.
        </p>
        <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          Ce n’est pas une contrainte technique, c’est une contrainte d’audit. Deux définitions
          concurrentes d’« impressions diffusées » ne rendent pas le système lent, elles le
          rendent inauditable — et la loi Sapin impose de pouvoir <em>montrer</em> comment un
          chiffre a été produit.
        </p>
      </Section>
    </>
  );
}
