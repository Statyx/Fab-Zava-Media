import { Section } from '@/components/Section';

/**
 * How the thing is wired, and what it cost to wire it.
 *
 * Second-rank in the nav on purpose: nobody opens a console to read an architecture. But the
 * two paragraphs at the bottom are the reason the page exists — the deployment negatives are
 * the most expensive thing anyone learned here, and they are exactly what gets asked in the
 * ten minutes after a demo lands.
 */
const CHAIN: { layer: string; item: string; note: string }[] = [
  { layer: 'Stockage', item: 'ZavaMediaLH', note: '11 tables, ~65 000 lignes, une seule copie' },
  { layer: 'Temps réel', item: 'RT_Zava_Media', note: 'événements de pacing, branchés sur la campagne' },
  { layer: 'Sémantique', item: 'SM_Zava_Media', note: '32 mesures — la définition unique du chiffre' },
  { layer: 'Ontologie', item: 'ONT_Zava_Media', note: '7 entités, 9 relations, parcours de graphe' },
  { layer: 'Analyse', item: 'Zava_Media_Analyst', note: 'agent de données Fabric — mesures et graphe' },
  { layer: 'Contrats', item: 'Zava-Media-Contracts', note: 'recherche vectorielle sur le corpus, A2A' },
  { layer: 'Orchestration', item: 'Zava-Media-Agent', note: 'superviseur Foundry — répartit et recolle' },
];

export function ArchitecturePage() {
  return (
    <>
      <Section id="chaine" title="La chaîne" provenance="Sweden Central — une seule région">
        <ol className="space-y-2">
          {CHAIN.map((c, i) => (
            <li
              key={c.item}
              className="grid grid-cols-[2rem_1fr] items-start gap-3 rounded-lg px-3 py-2"
              style={{ background: i % 2 ? 'transparent' : 'var(--bg-secondary)' }}
            >
              <span
                className="text-xs font-semibold tabular-nums"
                style={{ color: 'var(--text-muted)' }}
              >
                {String(i + 1).padStart(2, '0')}
              </span>
              <div>
                <p className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
                  {c.item}
                  <span className="ml-2 text-xs font-normal" style={{ color: 'var(--text-muted)' }}>
                    {c.layer}
                  </span>
                </p>
                <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                  {c.note}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </Section>

      <Section id="frontiere" title="La règle de frontière">
        <p className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          L’agent de données calcule et ne conclut pas. L’agent contractuel cite et ne calcule
          pas. Le superviseur ne fait ni l’un ni l’autre : il pose les deux questions et
          rapproche les réponses. Aucune couche ne peut produire seule une réponse à une
          question croisée, et c’est la propriété qui rend la chaîne auditable.
        </p>
        <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          Conséquence directe : le modèle sémantique ne contient aucun terme contractuel. Quand
          on lui demande un droit, il doit répondre que ce n’est pas dans ses données — et cette
          réponse-là est un succès, pas un échec.
        </p>
      </Section>

      <Section id="limites" title="Ce que le déploiement a réellement coûté">
        {/* Written down because a 200 is not a success, and the next person to run this will
            otherwise spend the same afternoon finding out. */}
        <ul className="space-y-3 text-sm" style={{ color: 'var(--text-secondary)' }}>
          <li>
            <strong style={{ color: 'var(--text-primary)' }}>
              Un déploiement d’infrastructure à 200 ne prouve rien ici.
            </strong>{' '}
            La connexion qui relie le superviseur à l’agent de données ne peut pas être créée
            par modèle : la catégorie n’existe pas côté infrastructure. Une étape manuelle dans
            le portail reste obligatoire, et l’automatisation qui prétend le contraire échoue
            plus tard, ailleurs, avec un message qui ne parle pas de connexion.
          </li>
          <li>
            <strong style={{ color: 'var(--text-primary)' }}>
              L’audience doit être déclarée au premier niveau.
            </strong>{' '}
            Rangée dans les métadonnées, elle est acceptée, stockée, puis ignorée. L’erreur
            arrive au moment de l’appel, avec un corps de réponse vide.
          </li>
          <li>
            <strong style={{ color: 'var(--text-primary)' }}>
              La propagation des droits répond 404, pas 403.
            </strong>{' '}
            Pendant plusieurs minutes après l’attribution du rôle, l’agent semble ne pas
            exister. La séquence observée est 404, 404, 404, 403, puis 200 — un 404 en début de
            déploiement ne veut donc pas dire que la ressource est absente.
          </li>
          <li>
            <strong style={{ color: 'var(--text-primary)' }}>
              Capacité en pause : 404 également.
            </strong>{' '}
            La vraie cause est enfouie dans le corps de la réponse. Vérifier la capacité avant
            de chercher ailleurs.
          </li>
          <li>
            <strong style={{ color: 'var(--text-primary)' }}>
              L’approbation d’outil se fait agent par agent.
            </strong>{' '}
            Elle est impossible depuis une exécution multi-agents, et l’échec ressemble à un
            défaut d’acheminement.
          </li>
        </ul>
      </Section>
    </>
  );
}
