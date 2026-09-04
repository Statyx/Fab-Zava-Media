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
    note: 'Due without the client asking — the agency has to initiate it.',
  },
  excluded: {
    label: 'Compensation excluded',
    tone: 'var(--sev-low)',
    note: 'Make-good, credit note and carry-over all expressly excluded.',
  },
  penalty: {
    label: 'Penalty borne by the agency',
    tone: 'var(--sev-high)',
    note: 'Due without prior formal notice.',
  },
};

export const AGREEMENTS: Agreement[] = [
  {
    id: 'ADV-001',
    advertiser: 'Contoso Mobility',
    regime: 'due',
    article: 'art. 6.1–6.2',
    summary:
      'Excess beyond the tolerance is not billable, and entitles the client to a make-good ' +
      'in space worth 50% of that excess, to be delivered within 45 days.',
  },
  {
    id: 'ADV-002',
    advertiser: 'Fabrikam Beauty',
    regime: 'penalty',
    article: 'art. 6.2',
    summary:
      'Under-delivery beyond the tolerance triggers a penalty of 2% of the net media ' +
      'budget, borne by the agency.',
  },
  {
    id: 'ADV-003',
    advertiser: 'Northwind Foods',
    regime: 'due',
    article: 'art. 6.1',
    summary: 'A variance beyond the tolerance gives rise to an adjustment.',
  },
  {
    id: 'ADV-004',
    advertiser: 'Litware Retail',
    regime: 'excluded',
    article: 'art. 6.3',
    summary:
      'Over-delivery is deemed to have no effect: no make-good, no credit note, no ' +
      'carry-over. Article 9.2 separately closes any invoice claim after 120 days.',
  },
  {
    id: 'ADV-005',
    advertiser: 'AdventureWorks Travel',
    regime: 'due',
    article: 'art. 6.1',
    summary: 'A variance beyond the tolerance gives rise to an adjustment.',
  },
];

export function agreementFor(advertiser: string): Agreement | undefined {
  return AGREEMENTS.find((a) => a.advertiser === advertiser);
}
