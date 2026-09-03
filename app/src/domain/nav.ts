import type { OpenerFamily } from '@/domain/openers';

/**
 * Route manifest.
 *
 * The sibling console shipped a first cut with two entries — Home and one "Cockpit" that
 * stacked every panel into a single scrolling column. Every card on the cover pointed at it,
 * so six different questions had one destination and the app read as a single screen with a
 * chat beside it. Do not reintroduce that under another name.
 *
 * The sections below are the four questions a media agency console is actually asked, in the
 * order they get asked:
 *
 *  - **Portefeuille** — where do things stand, and where do I start looking.
 *  - **Livraison**    — what was planned, what was delivered, and by how much it missed.
 *  - **Contrats**     — what the text says, with no figure in sight.
 *  - **Facturation**  — what was spent, what was billed, and what is about to lapse.
 *
 * There is exactly **one** navigation. The sibling app's worst structural failure was two
 * navigations over the same subject: a four-step arc holding every chart and no chat, beside
 * four personas holding every chat and no chart.
 *
 * The diagnostic route deliberately does NOT appear here. It exists, it is reachable by URL,
 * and it is not in the nav: a route nobody links to costs nothing on screen, and deleting it
 * would mean a rebuild plus a redeploy to get the diagnostic back at the exact moment the app
 * is already failing.
 */
export interface NavEntry {
  to: string;
  label: string;
  /** One line of what the section answers, shown under the page title. */
  blurb: string;
  icon: string;
}

/** Heroicons outline paths, 24x24. */
const HOME =
  'M2.25 12l8.954-8.955a1.5 1.5 0 012.122 0L22.28 12M4.5 9.75V19.5a1.5 1.5 0 001.5 1.5h3.75V16.5a1.5 1.5 0 011.5-1.5h1.5a1.5 1.5 0 011.5 1.5v4.5H18a1.5 1.5 0 001.5-1.5V9.75';
const CHART =
  'M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z';
const DOC =
  'M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z';
const EURO =
  'M14.121 15.536c-1.171 1.952-3.07 1.952-4.242 0-1.172-1.953-1.172-5.119 0-7.072 1.171-1.952 3.07-1.952 4.242 0M8 10.5h4m-4 3h4m9-1.5a9 9 0 11-18 0 9 9 0 0118 0z';
const GRAPH = 'M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5';
const PULSE = 'M2.25 12h3.75l3-9 4.5 18 3-9h5.25';
const OWNER =
  'M9 6.75V15m6-6v8.25m.503 3.498l4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 00-1.006 0L3.622 5.689C3.24 5.88 3 6.27 3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c.317-.159.69-.159 1.006 0l4.994 2.497c.317.158.69.158 1.006 0z';

export const NAV: NavEntry[] = [
  {
    to: '/portefeuille',
    label: 'Portefeuille',
    blurb: 'Où en sont les campagnes, et où regarder en premier.',
    icon: HOME,
  },
  {
    to: '/livraison',
    label: 'Livraison',
    blurb: 'Planifié contre livré, par marché et par trimestre — et le pacing en direct.',
    icon: CHART,
  },
  {
    to: '/contrats',
    label: 'Contrats',
    blurb: 'Les cinq contrats cadres et leurs trois régimes de compensation. Aucun chiffre.',
    icon: DOC,
  },
  {
    to: '/facturation',
    label: 'Facturation',
    blurb: 'Dépensé contre facturé, ce qui manque et la date à laquelle cela se périme.',
    icon: EURO,
  },
];

/** Not exported into NAV on purpose. */
export const DIAGNOSTIC_ROUTE = '/diagnostic';

/** Listed under the nav rather than in it: it explains the app, it is not part of the work. */
export const ARCHITECTURE_ROUTE = '/architecture';

/**
 * Which section answers a given family of question.
 *
 * The cover's cards are grouped by opener family, so this is the one table that decides where
 * a card lands. Keeping it here rather than in the page means a new family cannot be added
 * without the compiler pointing at this record.
 */
export const SECTION_BY_FAMILY: Record<OpenerFamily, string> = {
  portfolio: '/portefeuille',
  // The graph question is a traversal, not a figure — it belongs where the whole estate is in
  // view, not inside one quarter's variance table.
  graph: '/portefeuille',
  delivery: '/livraison',
  // Pacing shares the Livraison section because it is the same subject at a different tempo:
  // splitting it would produce two pages that each show half a delivery story.
  pacing: '/livraison',
  contract: '/contrats',
  billing: '/facturation',
};

/**
 * Two families share Portefeuille and two share Livraison, so the section alone would not tell
 * the user which card they clicked. The focus anchor scrolls the panel that answers it into
 * view and marks it for a couple of seconds.
 */
export const FOCUS_BY_FAMILY: Record<OpenerFamily, string> = {
  portfolio: 'mesures',
  graph: 'relations',
  delivery: 'ecarts',
  pacing: 'pacing',
  contract: 'regimes',
  billing: 'manquants',
};

export function routeForFamily(family: OpenerFamily): string {
  return SECTION_BY_FAMILY[family];
}

export function focusForFamily(family: OpenerFamily): string {
  return FOCUS_BY_FAMILY[family];
}

/**
 * The prefix the app is currently being served under.
 *
 * The design preview mounts the same screens a second time under `/preview`, so a link built
 * from a bare `NAV` entry jumps out of the preview and into the guarded app, which bounces to
 * sign-in. Every destination derived from `NAV` has to be prefixed with this, or navigating
 * the preview looks broken while the code is in fact correct.
 */
export function basePath(pathname: string): string {
  return pathname.startsWith('/preview') ? '/preview' : '';
}

/**
 * The human name of the section a card leads to.
 *
 * Printed on the card itself. Six cards that looked identical and all landed in the same place
 * was the original complaint; naming the destination on the card is what makes the difference
 * legible *before* the click, not after it.
 */
export function sectionLabelForFamily(family: OpenerFamily): string {
  const to = SECTION_BY_FAMILY[family];
  return NAV.find((n) => n.to === to)?.label ?? 'Ouvrir';
}

/**
 * The badge printed on a suggestion, before it is clicked.
 *
 * It answers "what will this go and read?" *in advance*, which is the question that makes one
 * question worth clicking rather than another. A wall of identical text pills tells the room
 * nothing about what separates them.
 *
 * Keyed on `family` rather than sniffed out of the `exercises` sentence: the family is typed,
 * so a new one cannot be added without the compiler stopping here, whereas a prose match would
 * quietly fall through to a default and mislabel the card.
 *
 * This is a *claim*, not evidence — it says what the question is expected to consult. What was
 * actually consulted is printed under the answer, and the two are allowed to disagree. That
 * disagreement is the interesting part and must stay visible.
 */
export interface OpenerBadge {
  label: string;
  icon: string;
  /** Theme token driving the badge tint. */
  tone: string;
}

const BADGE_BY_FAMILY: Record<OpenerFamily, OpenerBadge> = {
  portfolio: { label: 'Chiffres', icon: CHART, tone: 'var(--accent)' },
  delivery: { label: 'Chiffres + clauses', icon: CHART, tone: 'var(--sev-high)' },
  billing: { label: 'Chiffres + clauses', icon: EURO, tone: 'var(--sev-critical)' },
  graph: { label: 'Graphe de relations', icon: GRAPH, tone: 'var(--sev-low)' },
  contract: { label: 'Clauses', icon: DOC, tone: 'var(--sev-medium)' },
  pacing: { label: 'Flux temps réel', icon: PULSE, tone: 'var(--text-secondary)' },
};

export function badgeForFamily(family: OpenerFamily): OpenerBadge {
  return BADGE_BY_FAMILY[family];
}

export const OWNER_ICON = OWNER;
