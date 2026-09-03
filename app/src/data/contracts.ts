/**
 * The five master agreements, as the app displays them.
 *
 * This file holds **text**, never a figure. Every number on every screen comes from a measure
 * at runtime; every clause here comes from `design/contracts/ADV-00*.md`. That split is the
 * boundary rule of the whole demo, applied to the front end: Fabric computes, the corpus says
 * what it means, and the app is not allowed to blur the two.
 *
 * The consequences below are summaries for the cards. They are **not** the answer: when a user
 * asks what a variance entitles a client to, the answer must come back from the contract agent
 * with its own citation. A summary rendered from this file is a caption; an answer retrieved
 * from the corpus is evidence, and the app must never let the first pass for the second.
 */

export type Regime = 'due' | 'excluded' | 'penalty';

export interface Agreement {
  id: string;
  advertiser: string;
  /** The regime its delivery clause installs. */
  regime: Regime;
  article: string;
  /** One line, in the register an account director would use out loud. */
  summary: string;
}

/**
 * Three variances of the same order of magnitude, three opposite outcomes.
 *
 * This is the entire point of the demo and it is worth stating plainly: nothing in the
 * delivery figures predicts which regime applies, and nothing in the contracts predicts which
 * campaign will trip. Only the two together produce an answer, which is why the first card on
 * the cover is a `mixed` question.
 */
export const REGIME_STYLE: Record<Regime, { label: string; tone: string; note: string }> = {
  due: {
    label: 'Compensation due',
    tone: 'var(--sev-critical)',
    note: "Due sans demande du client — l'agence doit l'initier.",
  },
  excluded: {
    label: 'Compensation exclue',
    tone: 'var(--sev-low)',
    note: 'Compensation, avoir et report expressément exclus.',
  },
  penalty: {
    label: 'Pénalité à la charge de l’agence',
    tone: 'var(--sev-high)',
    note: 'Due sans mise en demeure préalable.',
  },
};

export const AGREEMENTS: Agreement[] = [
  {
    id: 'ADV-001',
    advertiser: 'Contoso Mobility',
    regime: 'due',
    article: 'art. 6.1–6.2',
    summary:
      "L'excédent au-delà de la tolérance n'est pas facturable, et ouvre droit à une " +
      "compensation en espace de 50 % de cet excédent, à livrer sous 45 jours.",
  },
  {
    id: 'ADV-002',
    advertiser: 'Fabrikam Beauty',
    regime: 'penalty',
    article: 'art. 6.2',
    summary:
      "Une sous-livraison au-delà de la tolérance déclenche une pénalité de 2 % du budget " +
      "média net, due par l'agence.",
  },
  {
    id: 'ADV-003',
    advertiser: 'Northwind Foods',
    regime: 'due',
    article: 'art. 6.1',
    summary: "L'écart au-delà de la tolérance donne lieu à régularisation.",
  },
  {
    id: 'ADV-004',
    advertiser: 'Litware Retail',
    regime: 'excluded',
    article: 'art. 6.3',
    summary:
      "La sur-livraison est réputée sans effet : ni compensation, ni avoir, ni report. " +
      "L'article 9.2 ferme par ailleurs toute réclamation de facture passé 120 jours.",
  },
  {
    id: 'ADV-005',
    advertiser: 'AdventureWorks Travel',
    regime: 'due',
    article: 'art. 6.1',
    summary: "L'écart au-delà de la tolérance donne lieu à régularisation.",
  },
];

export function agreementFor(advertiser: string): Agreement | undefined {
  return AGREEMENTS.find((a) => a.advertiser === advertiser);
}
