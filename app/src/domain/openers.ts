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
 * Prompts are written in English because the answer comes back in the language it was asked
 * in, and this console is English. Switching this file back to another language switches the
 * agents' answers with it — that is the only lever. The identifiers inside the prompts keep
 * their real spelling in every language: translating `dim_campaign` would simply stop it
 * resolving.
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

/**
 * Which console the question actually has to be asked of.
 *
 * `fabric`  — the Fabric data agent. It reaches the semantic model, the ontology and the
 *             Eventhouse. Three sources, so a `fabric` question can still cross: pacing
 *             against the delivery figures is a genuine cross that never leaves Fabric.
 * `foundry` — the Foundry supervisor, because the answer needs a contract clause. The
 *             contract corpus sits behind an A2A subordinate that only the supervisor can
 *             reach; `foundry/deploy_foundry_agents.py` explains at length why it had to be
 *             a separate agent rather than a `file_search` tool on the supervisor.
 *
 * This is deliberately NOT derived from `kind`. `kind` is what the room is told — one source
 * or several — and `backend` is who can answer. They came apart in practice: `pacing-vs-batch`
 * is `mixed` and pure Fabric, while `contract-regimes` is `single` and unanswerable by Fabric.
 * Deriving one from the other sent every contract question to an agent that cannot read
 * contracts, which the agent then said out loud, on screen: "I cannot see any delivery clauses
 * or client entitlements in this dataset".
 */
export type OpenerBackend = 'fabric' | 'foundry';

export interface Opener {
  id: string;
  family: OpenerFamily;
  kind: OpenerKind;
  backend: OpenerBackend;
  /**
   * 1 — an entry point, offered before anything has been asked.
   * 2 — digs into the answer a specific depth-1 question just produced.
   *
   * The split exists because the two are not interchangeable. An entry point has to stand
   * alone in front of a cold room; a depth-2 question assumes the figure on screen and would
   * be meaningless as an opening card. Flattening them into one list is how the sibling demo
   * ended up offering "and what does the previous quarter say?" as its first click.
   */
  depth: 1 | 2;
  /** Depth-2 only: the opener whose answer this one interrogates. */
  parent?: string;
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
  ' Answer the way an account director prepares a client review, in 90 words at most: ' +
  'the conclusion first, then only the two or three figures that carry it. ' +
  'Always give planned and delivered alongside a percentage. Do not list rows. ' +
  'In the prose, name advertisers, markets and media owners the way they are said out loud, ' +
  'with no identifier, table name or measure name. Finish with a single `### SOURCE` block ' +
  'of six lines at most, carrying the identifiers, tables and measures used.';

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
    backend: 'foundry',
    depth: 1,
    label: 'Which markets are off plan in Q3, and what does the contract say about it?',
    prompt:
      'Which advertiser x market pairs are off plan for the 2026-Q3 quarter? ' +
      'Use [Planned Impressions], [Delivered Impressions] and [Delivery vs Plan %] by ' +
      'dim_advertiser[advertiser_name] and dim_market[market_name], filtered on ' +
      'dim_campaign[quarter] = "2026-Q3". For each variance found, go and read in the master ' +
      'agreements what the delivery clause provides for, and say whether the client is ' +
      'entitled to anything or not.' +
      HOUSE_STYLE,
    exercises: 'the delivery figures, then the master agreements',
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
    backend: 'foundry',
    depth: 1,
    label: 'What ran and was never billed, and how long can it still be claimed?',
    prompt:
      'What is the gap between what was spent and what was billed? Use ' +
      '[Net Spend (EUR)], [Net Billed (EUR)] and [Billing vs Spend Gap (EUR)] by ' +
      'dim_advertiser[advertiser_name] and dim_market[market_name]. State how many distinct ' +
      'campaigns are affected and how many fact_billing rows are missing, saying explicitly ' +
      'that those two counts are not at the same grain. Then go and read, in the affected ' +
      "advertiser's contract, the deadline beyond which an omitted invoice can no longer be " +
      'claimed, and the date that deadline expires.' +
      HOUSE_STYLE,
    exercises: 'billing, then the claim deadline in the contract',
  },

  {
    id: 'portfolio-state',
    family: 'portfolio',
    kind: 'single',
    backend: 'fabric',
    depth: 1,
    label: 'Where does the portfolio stand over the period?',
    prompt:
      'Give the state of the portfolio over the period: [Total Campaigns], ' +
      '[Active Campaigns], [Planned Budget (EUR)], [Net Spend (EUR)], ' +
      '[Budget Consumption %], then [Over-delivered Campaigns] and ' +
      '[Under-delivered Campaigns]. Say where the risk is concentrated.' +
      HOUSE_STYLE,
    exercises: 'the portfolio measures',
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
    backend: 'fabric',
    depth: 1,
    label: 'Which media owners carry the campaigns in the off-plan market?',
    prompt:
      'Which media owners sold the Contoso Mobility campaigns in Spain? Follow the ' +
      'graph: Advertiser -[AdvertiserHasBrand]-> Brand -[BrandHasCampaign]-> Campaign, ' +
      'then Campaign -[CampaignInMarket]-> Market to keep only MKT-ES, and finally ' +
      'Campaign -[CampaignBooksMediaOwner]-> MediaOwner. Name each media owner and its type.' +
      HOUSE_STYLE,
    exercises: 'the advertiser - brand - campaign - media owner graph',
  },

  /**
   * `single` and yet `foundry`, which is the pair that broke the earlier routing.
   *
   * One source — the contract corpus — so the room is correctly told this is not a cross. But
   * that source is not one the Fabric data agent can reach, so the question has to go to the
   * supervisor anyway. Routed on `kind` alone it went to Fabric and came back with the agent
   * politely explaining, on screen, that it cannot see contract clauses.
   */
  {
    id: 'contract-regimes',
    family: 'contract',
    kind: 'single',
    backend: 'foundry',
    depth: 1,
    label: 'What do the contracts provide for in case of over-delivery?',
    prompt:
      'Across the five indexed master agreements, what does each one provide for in case of ' +
      'a delivery variance? Distinguish the regimes: compensation due without the client ' +
      'asking, compensation expressly excluded, and penalty borne by the agency. Cite the ' +
      'article for each one. Use no delivery figure: this question is about the text alone.' +
      HOUSE_STYLE,
    exercises: 'the five master agreements',
  },

  {
    id: 'pacing-live',
    family: 'pacing',
    kind: 'single',
    backend: 'fabric',
    depth: 1,
    label: 'What is pacing reporting right now?',
    prompt:
      'What is the pacing stream reporting? From the pacing_events table in the Eventhouse, ' +
      'give per campaign_id the average pacing_index, the total impressions_delta and ' +
      'spend_delta, and the earliest and latest timestamp, keeping only campaigns whose ' +
      'average pacing_index is above 1. Keep it to one summarize, no join. Then say which ' +
      'campaigns are over-consuming and how many days the window covers. Resolve the ' +
      'campaign codes to names with a separate semantic model query, never inside the KQL.' +
      HOUSE_STYLE,
    exercises: 'the real-time pacing stream',
  },

  /* ── Depth 2 ────────────────────────────────────────────────────────────────────────────
   *
   * Two per opener, offered only once that opener has answered.
   *
   * They are written to assume the figure already on screen, which is what makes them worth
   * a click: "where did it come from" is a good second question and a terrible first one.
   *
   * Each pair splits: the first child narrows the figure the parent produced, the second one
   * crosses into a second source. The split is enforced by a test rather than by this comment.
   *
   * The cross is into the contract corpus for five families out of six, which is the only
   * moment the room sees a number and a clause meet — the whole commercial argument of the
   * demo. Pacing is the exception and an honest one: its cross is the Eventhouse stream
   * against the semantic model, two sources that are both Fabric's.
   *
   * An earlier version of this comment claimed the pairs already split that way. They did not
   * — four families out of six had two Fabric children and never crossed at all, so the second
   * click only ever produced more of the same table.
   */

  {
    id: 'variance-breakdown',
    family: 'delivery',
    kind: 'single',
    backend: 'fabric',
    depth: 2,
    parent: 'variance-remedy',
    label: 'Where did that overshoot actually come from?',
    prompt:
      'For the Contoso Mobility campaigns in Spain over 2026-Q3, break the delivery down by ' +
      'dim_channel[channel_name] and dim_media_owner[media_owner_name]. Give ' +
      '[Planned Impressions], [Delivered Impressions] and [Delivery vs Plan %] for each, and ' +
      'say which channel and which media owner carry most of the [Impression Gap].' +
      HOUSE_STYLE,
    exercises: 'the delivery figures, by channel and media owner',
  },
  /**
   * The delivery cross, and the one that reframes the parent's answer.
   *
   * The supervisor volunteered the hook when probed: "Northwind Foods considers only annual
   * totals, so no remedies arise from these quarterly differences." The quarter is our
   * reporting grain, not necessarily the contractual one — so a quarterly overshoot can be
   * loud on the dashboard and not be an event at all under the agreement. No figure says
   * that, and the clause alone does not either.
   */
  {
    id: 'variance-precedent',
    family: 'delivery',
    kind: 'mixed',
    backend: 'foundry',
    depth: 2,
    parent: 'variance-remedy',
    label: 'Is a quarterly overshoot even what the contract measures?',
    prompt:
      'Compare 2026-Q2 and 2026-Q3 for the same advertiser x market pairs. Use ' +
      '[Planned Impressions], [Delivered Impressions] and [Delivery vs Plan %] by ' +
      'dim_advertiser[advertiser_name], dim_market[market_name] and dim_campaign[quarter], ' +
      'and say which variances are new this quarter and which were already there. Then go and ' +
      'read, in each of those advertisers\' master agreements, over what period the delivery ' +
      'variance is actually assessed — per quarter, per campaign or over the year — and say ' +
      'for which advertisers the quarterly figure on screen is not yet a contractual event.' +
      HOUSE_STYLE,
    exercises: 'the delivery figures quarter over quarter, then the measurement period in the contracts',
  },

  {
    id: 'unbilled-owners',
    family: 'billing',
    kind: 'single',
    backend: 'fabric',
    depth: 2,
    parent: 'unbilled-window',
    label: 'Who is sitting on the unbilled amount?',
    prompt:
      'Break the billing gap down by dim_media_owner[media_owner_name] and by month. Use ' +
      '[Net Spend (EUR)], [Net Billed (EUR)] and [Billing vs Spend Gap (EUR)]. Say which ' +
      'media owners and which months concentrate the gap, and whether it is one large ' +
      'omission or many small ones.' +
      HOUSE_STYLE,
    exercises: 'billing, by media owner and month',
  },
  /**
   * The billing cross, and the one an agency finance director asks first.
   *
   * The rebate rate we actually applied is a figure; the rate the agreement stipulates is a
   * clause. Nobody in the room can tell whether they match by looking at either one alone,
   * and a gap between them is money in the wrong direction on every invoice already sent.
   */
  {
    id: 'unbilled-rebate',
    family: 'billing',
    kind: 'mixed',
    backend: 'foundry',
    depth: 2,
    parent: 'unbilled-window',
    label: 'Does the rebate we applied match the rate the contract sets?',
    prompt:
      'For the advertisers carrying the billing gap, give [Gross Billed (EUR)], ' +
      '[Rebate Amount (EUR)], [Rebate % of Gross] and [Net Net Billed (EUR)] by ' +
      'dim_advertiser[advertiser_name]. Then go and read, in each of those advertisers\' ' +
      'master agreements, the volume rebate the agreement actually provides for — the rate ' +
      'and the threshold that triggers it. Say for which advertisers the applied rate and the ' +
      'contractual rate disagree, and in whose favour.' +
      HOUSE_STYLE,
    exercises: 'the rebate measures, then the rebate clause in the contracts',
  },

  {
    id: 'portfolio-concentration',
    family: 'portfolio',
    kind: 'single',
    backend: 'fabric',
    depth: 2,
    parent: 'portfolio-state',
    label: 'Where is the budget concentrated?',
    prompt:
      'Which advertisers and which markets concentrate the spend? Use ' +
      '[Planned Budget (EUR)], [Net Spend (EUR)] and [Budget Consumption %] by ' +
      'dim_advertiser[advertiser_name] and dim_market[market_name]. Say how much of the ' +
      'portfolio the top advertisers represent, and whether the risk found earlier sits ' +
      'inside that concentration or outside it.' +
      HOUSE_STYLE,
    exercises: 'the portfolio measures, by advertiser and market',
  },
  /**
   * The portfolio cross.
   *
   * This question used to ask about disputed invoices, and it was unanswerable: `[Disputed
   * Invoices]` counts `invoice_status = "Disputed"`, and the generator only ever emits `Paid`
   * and `Issued`. The agent said so, politely, on the second click of the portfolio thread.
   *
   * So it asks about the invoices that really are outstanding — 161 of them — and crosses to
   * the clause that decides whether outstanding is late: an unpaid invoice is a number until
   * you know how long the client contractually has to settle it.
   */
  {
    id: 'portfolio-unpaid',
    family: 'billing',
    kind: 'mixed',
    backend: 'foundry',
    depth: 2,
    parent: 'portfolio-state',
    label: 'Which invoices are past their payment window?',
    prompt:
      'Give [Total Invoices] and [Net Billed (EUR)] by dim_advertiser[advertiser_name], split ' +
      'on fact_billing[invoice_status], and say how much is still outstanding and how old the ' +
      'oldest unsettled invoice is, using fact_billing[invoice_date]. Then go and read, in ' +
      'those advertisers\' master agreements, the payment term: how many days after the ' +
      'invoice date the client has to settle. Say whose outstanding invoices are now past ' +
      'that window and whose are still inside it.' +
      HOUSE_STYLE,
    exercises: 'the invoice measures, then the payment terms in the contracts',
  },

  {
    id: 'graph-shared-owners',
    family: 'graph',
    kind: 'single',
    backend: 'fabric',
    depth: 2,
    parent: 'graph-owners',
    label: 'Which media owners do several advertisers depend on?',
    prompt:
      'Which media owners are booked by more than one advertiser? Follow the graph: ' +
      'MediaOwner <-[CampaignBooksMediaOwner]- Campaign <-[BrandHasCampaign]- Brand ' +
      '<-[AdvertiserHasBrand]- Advertiser. Name the media owners reached by several distinct ' +
      'advertisers and say what that concentration exposes if one of them under-delivers.' +
      HOUSE_STYLE,
    exercises: 'the media owner - campaign - brand - advertiser graph',
  },
  /**
   * The graph cross, and the only question in the set where the two sources can contradict
   * each other outright.
   *
   * The graph says which brands actually ran. The agreement says which brands are in scope.
   * A brand that ran and is not named in the scope is work delivered outside the contract —
   * which is a commercial conversation, not a reporting one. Neither side can raise it alone.
   */
  {
    id: 'graph-brand-path',
    family: 'graph',
    kind: 'mixed',
    backend: 'foundry',
    depth: 2,
    parent: 'graph-owners',
    label: 'Are all those brands actually in the contract scope?',
    prompt:
      'For Contoso Mobility, follow Advertiser -[AdvertiserHasBrand]-> Brand ' +
      '-[BrandHasCampaign]-> Campaign -[CampaignInMarket]-> Market, and name each brand, its ' +
      'campaigns and the markets they run in. Then go and read, in that advertiser\'s master ' +
      'agreement, which brands and which markets the agreement actually covers. Say whether ' +
      'every brand that ran is named in the scope, and flag any brand or market that ran ' +
      'without being covered.' +
      HOUSE_STYLE,
    exercises: 'the brand graph, then the scope clause in the contract',
  },

  {
    id: 'contract-deadlines',
    family: 'contract',
    kind: 'single',
    backend: 'foundry',
    depth: 2,
    parent: 'contract-regimes',
    label: 'What deadlines do those clauses run on?',
    prompt:
      'Across the five indexed master agreements, what notice periods and claim windows does ' +
      'each one set for a delivery variance or an omitted invoice? Give the article and the ' +
      'duration for each, and say which agreement is the most restrictive. Use no figure from ' +
      'the delivery or billing data: this question is about the text alone.' +
      HOUSE_STYLE,
    exercises: 'the five master agreements',
  },
  {
    id: 'contract-triggered',
    family: 'contract',
    kind: 'mixed',
    backend: 'foundry',
    depth: 2,
    parent: 'contract-regimes',
    label: 'Which of those clauses are actually triggered today?',
    prompt:
      'Take the delivery variances observed in the 2026-Q3 quarter — use [Delivery vs Plan %] ' +
      'and [Impression Gap] by dim_advertiser[advertiser_name] and dim_market[market_name], ' +
      'filtered on dim_campaign[quarter] = "2026-Q3" — and for each one go and read the clause ' +
      'of that advertiser\'s master agreement. Say which clauses are actually triggered by the ' +
      'figures and which are not, and name the ones where the agency owes rather than the ' +
      'client.' +
      HOUSE_STYLE,
    exercises: 'the delivery figures, then the master agreements',
  },

  {
    id: 'pacing-window',
    family: 'pacing',
    kind: 'single',
    backend: 'fabric',
    depth: 2,
    parent: 'pacing-live',
    label: 'How has the pacing index moved across the window?',
    prompt:
      'From the pacing_events table in the Eventhouse, run two separate simple queries and do ' +
      'not combine them in KQL. First: the average pacing_index by campaign_id and by hourly ' +
      'bin of timestamp, ordered by campaign then time. Second: keep only rows where ' +
      'pacing_index is above 1, then per campaign_id give the earliest timestamp, the latest ' +
      'timestamp and the highest pacing_index. Read the trend off those two result sets ' +
      'yourself: say where the window starts and ends, when each campaign first went above 1, ' +
      'and whether it is still climbing or has settled. Resolve the campaign codes to names ' +
      'with a separate semantic model query, never inside the KQL.' +
      HOUSE_STYLE,
    exercises: 'the real-time pacing stream, over time',
  },
  /**
   * `mixed` and yet `fabric` — the counterexample that keeps `kind` and `backend` apart.
   *
   * This one genuinely crosses two sources, and the room should be told so, but both sources
   * are Fabric's: the Eventhouse stream against the semantic model. Sending it to the
   * supervisor would add an A2A hop that has nothing to contribute and forty seconds of
   * latency to prove it.
   */
  {
    id: 'pacing-vs-batch',
    family: 'pacing',
    kind: 'mixed',
    backend: 'fabric',
    depth: 2,
    parent: 'pacing-live',
    label: 'Does the live stream agree with the delivery figures?',
    prompt:
      'Compare the two sources for the same campaigns. From the Eventhouse, sum ' +
      'impressions_delta from pacing_events. From the semantic model, give ' +
      '[Delivered Impressions] and [Delivery vs Plan %]. Say whether the live stream and the ' +
      'batch figures point the same way, and be explicit that they do not cover the same ' +
      'period — the stream is a short live window and the model is the whole campaign.' +
      HOUSE_STYLE,
    exercises: 'the pacing stream and the delivery figures, side by side',
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
  portfolio: { icon: '🎯', accent: '#00008F', area: 'Portfolio' },
  delivery: { icon: '📐', accent: '#027180', area: 'Delivery' },
  pacing: { icon: '📈', accent: '#0891b2', area: 'Pacing' },
  graph: { icon: '🕸️', accent: '#0369a1', area: 'Relationships' },
  contract: { icon: '📜', accent: '#896610', area: 'Contracts' },
  billing: { icon: '💶', accent: '#863C41', area: 'Billing' },
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

/** Entry points only. A depth-2 question as a first card assumes a figure nobody has seen. */
export function entryPoints(pool: Opener[] = OPENERS): Opener[] {
  return pool.filter((o) => o.depth === 1);
}

/** Before the first question: 3 starters. More is a decision, and a live demo stalls on it. */
export function starters(pool: Opener[] = OPENERS): Opener[] {
  return selectOpeners(entryPoints(pool)).slice(0, 3);
}

/**
 * The two questions that dig into the answer just given.
 *
 * Returns nothing for a typed question, and nothing once both have been asked. That emptiness
 * is deliberate rather than a gap to backfill: offering "where did that come from?" against an
 * answer the console did not produce would attach a real-looking follow-up to a question it
 * knows nothing about.
 */
export function deeper(
  lastOpenerId: string | null,
  asked: string[],
  pool: Opener[] = OPENERS
): Opener[] {
  if (!lastOpenerId) return [];
  const askedSet = new Set(asked);
  return pool.filter(
    (o) => o.depth === 2 && o.parent === lastOpenerId && !askedSet.has(o.id)
  );
}

/**
 * The other subjects still on the table, minus what was already asked.
 *
 * Kept alongside `deeper` rather than replaced by it. Digging is the point of the second
 * click, but a rail that only ever digs walks the room down one branch and never shows the
 * graph, the contracts or the live stream — three of the six things the demo exists to
 * demonstrate. Showing none empties the rail exactly when the audience has just learned what
 * a good question is.
 */
export function followUps(asked: string[], pool: Opener[] = OPENERS): Opener[] {
  const askedSet = new Set(asked);
  const remaining = entryPoints(pool).filter((o) => !askedSet.has(o.id));
  const perFamily = selectOpeners(remaining);
  const extra = remaining.filter((o) => !perFamily.includes(o));
  return [...perFamily, ...extra].slice(0, 3);
}
