/**
 * Questions the user can hand to the assistant.
 *
 * Every opener carries two registers:
 *  - `prompt` — names the table and the column explicitly, so the agent never has to guess
 *    which reading of a domain phrase we meant.
 *  - `label`  — what the room reads. Plain business language, no identifier.
 *
 * This is not politeness. The sibling demo recorded three *correct* answers to "how many are
 * at risk" depending on which column was read: an unscoped question is under-specified, not
 * unstable. Zava has the same trap and a sharper one — `fact_billing` is grained
 * campaign x media owner x month, so "how many campaigns were never billed" answers 2 while
 * "how many rows are missing" answers 6, and both are right.
 *
 * Plain language must not upgrade a claim: a label never says the app *observed* something it
 * merely declares. What actually ran is printed under the answer.
 *
 * Prompts are written in French because the answer comes back in the language it was asked
 * in, and the room is French. The identifiers inside them keep their real spelling —
 * translating `dim_campaign` would simply stop it resolving.
 */
export type OpenerFamily =
  | 'portfolio'
  | 'delivery'
  | 'pacing'
  | 'graph'
  | 'contract'
  | 'billing';

/**
 * `mixed` openers force more than one subordinate to fire — a figure from the semantic model
 * *and* a clause from the contract corpus.
 *
 * They are the only questions that give the supervisor real work. A supervisor with one
 * reachable source is a relay: every question becomes a forty-second pass-through with
 * nothing to cross-reference. The entry screen must demonstrate the product, not describe it,
 * so the first card is `mixed`.
 */
export type OpenerKind = 'mixed' | 'single';

export interface Opener {
  id: string;
  family: OpenerFamily;
  kind: OpenerKind;
  label: string;
  prompt: string;
  /**
   * One line naming what this question is expected to consult, in agency language.
   *
   * Shown *before* the question is sent, and phrased as a claim about data ("the delivery
   * figures", "the master agreements") rather than about products. The room is watching a
   * media agency console, not a Fabric architecture review. What matters is that the
   * expectation is stated up front and can be contradicted afterwards by what actually ran.
   */
  exercises: string;
}

/**
 * The house style, appended to every prompt.
 *
 * Written once and shared, because it is a rule about the console rather than a detail of any
 * one question — six copies would drift, and the first to drift would be the one on screen.
 *
 * It restates, in the agent's own register, what `foundry/verify_foundry.py ::
 * check_answer_contract` enforces structurally: exactly one `### SOURCE` block, no identifier
 * in the prose, no full-precision ratio. The check is the backstop, not the instruction — an
 * answer that only fails at verification has already been read aloud.
 *
 * It describes the **write-up**, never the tooling. An earlier attempt in the sibling app
 * said "never name the tooling that produced the answer"; the agent read that as an
 * instruction about its own behaviour, consulted nothing, and returned in 29.5 s.
 */
export const HOUSE_STYLE =
  " Réponds comme un directeur de clientèle prépare un point client, en 90 mots au plus : " +
  "la conclusion d'abord, puis seulement les deux ou trois chiffres qui la portent. " +
  "Donne toujours le planifié et le livré à côté d'un pourcentage. N'énumère pas de lignes. " +
  "Dans la prose, nomme les annonceurs, marchés et régies comme on les dit à l'oral, sans " +
  "aucun identifiant, nom de table ni nom de mesure. Termine par un unique bloc " +
  "`### SOURCE` de six lignes au maximum, qui porte les identifiants, les tables et les " +
  "mesures utilisées.";

export const OPENERS: Opener[] = [
  /**
   * First card, and `mixed` on purpose.
   *
   * Three variances of the same order of magnitude produce three opposite outcomes: Contoso
   * is owed a make-good, Litware is owed nothing, and on Fabrikam the agency owes a penalty.
   * No figure implies that, and no clause implies it either — it only appears when the two
   * are put side by side. That is the demo, in one click.
   */
  {
    id: 'variance-remedy',
    family: 'delivery',
    kind: 'mixed',
    label: 'Quels marchés dérapent au T3, et que prévoit le contrat en face ?',
    prompt:
      "Quels couples annonceur x marché s'écartent du plan sur le trimestre 2026-Q3 ? " +
      'Utilise [Planned Impressions], [Delivered Impressions] et [Delivery vs Plan %] par ' +
      'dim_advertiser[advertiser_name] et dim_market[market_name], filtré sur ' +
      'dim_campaign[quarter] = "2026-Q3". Pour chaque écart trouvé, va chercher dans les ' +
      'contrats cadres ce que la clause de livraison prévoit, et dis si le client a droit à ' +
      'quelque chose ou non.' +
      HOUSE_STYLE,
    exercises: 'les chiffres de livraison, puis les contrats cadres',
  },

  /**
   * Second `mixed`, and the one that carries a deadline.
   *
   * The figure alone is a number on a slide. The figure plus the claim window is a date after
   * which the money is gone, which is a different conversation.
   */
  {
    id: 'unbilled-window',
    family: 'billing',
    kind: 'mixed',
    label: "Qu'est-ce qui a été diffusé et jamais facturé, et jusqu'à quand est-ce réclamable ?",
    prompt:
      "Quel est l'écart entre ce qui a été dépensé et ce qui a été facturé ? Utilise " +
      '[Net Spend (EUR)], [Net Billed (EUR)] et [Billing vs Spend Gap (EUR)] par ' +
      'dim_advertiser[advertiser_name] et dim_market[market_name]. Précise combien de ' +
      'campagnes distinctes sont concernées et combien de lignes de fact_billing manquent, ' +
      "en disant que ces deux comptes ne sont pas au même grain. Puis va chercher dans le " +
      "contrat de l'annonceur concerné le délai au-delà duquel une facture omise ne peut " +
      'plus être réclamée, et la date à laquelle ce délai expire.' +
      HOUSE_STYLE,
    exercises: 'la facturation, puis le délai de forclusion au contrat',
  },

  {
    id: 'portfolio-state',
    family: 'portfolio',
    kind: 'single',
    label: 'Où en est le portefeuille sur la période ?',
    prompt:
      "Donne l'état du portefeuille sur la période : [Total Campaigns], [Active Campaigns], " +
      '[Planned Budget (EUR)], [Net Spend (EUR)], [Budget Consumption %], puis ' +
      '[Over-delivered Campaigns] et [Under-delivered Campaigns]. Dis où se concentre le ' +
      'risque.' +
      HOUSE_STYLE,
    exercises: 'les mesures du portefeuille',
  },

  /**
   * The graph question.
   *
   * Copied from the phrasings in `fabric/data_agent/deploy_data_agent.py :: FEWSHOTS` rather
   * than rewritten: in the sibling demo the first twenty canned questions all *looked*
   * relational and not one of them left the semantic model. A question that merely looks like
   * a graph question is not one.
   *
   * The traversal is spelled out because the model deliberately has no direct
   * Campaign -> Advertiser shortcut: the advertiser is reached through the brand.
   */
  {
    id: 'graph-owners',
    family: 'graph',
    kind: 'single',
    label: 'Quelles régies portent les campagnes du marché en écart ?',
    prompt:
      'Quelles régies ont vendu les campagnes de Contoso Mobility en Espagne ? Suis le ' +
      'graphe : Advertiser -[AdvertiserHasBrand]-> Brand -[BrandHasCampaign]-> Campaign, ' +
      'puis Campaign -[CampaignInMarket]-> Market pour ne garder que MKT-ES, et enfin ' +
      'Campaign -[CampaignBooksMediaOwner]-> MediaOwner. Nomme chaque régie et son type.' +
      HOUSE_STYLE,
    exercises: 'le graphe annonceur - marque - campagne - régie',
  },

  {
    id: 'contract-regimes',
    family: 'contract',
    kind: 'single',
    label: 'Que prévoient les contrats en cas de sur-livraison ?',
    prompt:
      "Dans les cinq contrats cadres indexés, que prévoit chacun en cas d'écart de " +
      'livraison ? Distingue les régimes : compensation due sans demande du client, ' +
      "compensation expressément exclue, et pénalité à la charge de l'agence. Cite " +
      "l'article pour chacun. N'utilise aucun chiffre de livraison : cette question porte " +
      'sur le texte seul.' +
      HOUSE_STYLE,
    exercises: 'les cinq contrats cadres',
  },

  {
    id: 'pacing-live',
    family: 'pacing',
    kind: 'single',
    label: 'Que remonte le pacing en ce moment ?',
    prompt:
      "Que remonte le flux de pacing ? Utilise la table pacing_events de l'Eventhouse : " +
      'timestamp, campaign_id, impressions_delta, spend_delta et pacing_index. Dis quelles ' +
      'campagnes sur-consomment leur plan et depuis quand, et dis combien de temps couvre ' +
      'la fenêtre que tu as lue.' +
      HOUSE_STYLE,
    exercises: 'le flux de pacing temps réel',
  },
];

/**
 * How each family presents itself.
 *
 * Kept beside the openers for the same reason `severity.ts` owns its colour map: two screens
 * that each invent an icon for "billing" drift apart within a week. `area` is the human name
 * of the investigation, not the technical family key.
 *
 * The accents are the house persona accents from the sibling app, reused unchanged.
 */
export const FAMILY_STYLE: Record<
  OpenerFamily,
  { icon: string; accent: string; area: string }
> = {
  portfolio: { icon: '🎯', accent: '#00008F', area: 'Portefeuille' },
  delivery: { icon: '📐', accent: '#027180', area: 'Livraison' },
  pacing: { icon: '📈', accent: '#0891b2', area: 'Pacing' },
  graph: { icon: '🕸️', accent: '#0369a1', area: 'Relations' },
  contract: { icon: '📜', accent: '#896610', area: 'Contrats' },
  billing: { icon: '💶', accent: '#863C41', area: 'Facturation' },
};

/**
 * One opener per family — never `slice(0, n)`.
 *
 * A cap over a curated list does not sample it, it truncates it, and it fails silently: in
 * the sibling app the registry happened to list its graph questions last, so a `slice(0, 3)`
 * removed every path to the ontology from every persona's openers. The graph stopped being
 * demonstrable and nothing failed to say so.
 *
 * The test pins **family coverage**, not the count.
 */
export function selectOpeners(pool: Opener[] = OPENERS): Opener[] {
  const seen = new Set<OpenerFamily>();
  const picked: Opener[] = [];
  for (const o of pool) {
    if (seen.has(o.family)) continue;
    seen.add(o.family);
    picked.push(o);
  }
  return picked;
}

/** Before the first question: 3 starters. More is a decision, and a live demo stalls on it. */
export function starters(pool: Opener[] = OPENERS): Opener[] {
  return selectOpeners(pool).slice(0, 3);
}

/**
 * After each answer: 3 chips, minus what was already asked. Showing none empties the rail
 * exactly when the audience has just learned what a good question is.
 */
export function followUps(asked: string[], pool: Opener[] = OPENERS): Opener[] {
  const askedSet = new Set(asked);
  const remaining = pool.filter((o) => !askedSet.has(o.id));
  const perFamily = selectOpeners(remaining);
  const extra = remaining.filter((o) => !perFamily.includes(o));
  return [...perFamily, ...extra].slice(0, 3);
}
