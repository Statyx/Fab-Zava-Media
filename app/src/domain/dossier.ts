export type DossierStep = 'facts' | 'contract' | 'work' | 'web' | 'action';
export type EvidenceMode = 'repository' | 'recorded' | 'live';

export interface WorkNote {
  id: string;
  caseId: string;
  advertiserId: string;
  marketId: string;
  quarter: string;
  date: string;
  authorRole: string;
  nextRole: string;
  status: string;
  text: string;
  simulated: boolean;
}

export interface WebNote {
  id: string;
  caseId: string;
  advertiserId: string;
  marketId: string;
  quarter: string;
  publishedOn: string;
  source: string;
  headline: string;
  summary: string;
  meetingPrompt: string;
  simulated: boolean;
}

export interface WebContext {
  scenarioId: string;
  asOf: string;
  simulated: boolean;
  fingerprint: string;
  notes: WebNote[];
}

export type WorkSignalKind = 'email' | 'teams' | 'meeting' | 'file';

export interface WorkSignal {
  id: string;
  kind: string;
  date: string;
  who: string;
  title: string;
  detail: string;
}

export interface WorkCase {
  caseId: string;
  advertiserId: string;
  marketId: string;
  quarter: string;
  simulated: boolean;
  impact: string;
  nextStep: string;
  signals: WorkSignal[];
  people: { name: string; role: string }[];
  recipient: { name: string; role: string; channel: string; reasons: string[] };
}

export interface WorkContext {
  scenarioId: string;
  asOf: string;
  simulated: boolean;
  fingerprint: string;
  cases: WorkCase[];
}

export interface DossierCase {
  id: string;
  advertiserId: string;
  advertiser: string;
  marketId: string;
  market: string;
  quarter: string;
  campaignIds: string[];
  campaigns: { id: string; name: string; brand: string }[];
  facts: { planned: number; delivered: number; variance: number };
  contract: {
    file: string;
    reference: string;
    treatment: string;
    fingerprint: string;
    articles: { number: string; text: string }[];
  };
}

export interface DossierInput {
  scenarioId: string;
  asOf: string;
  kind: string;
  fingerprint: string;
  scopeFingerprint: string;
  cases: DossierCase[];
  workNotes: WorkNote[];
}

export interface DossierCapture {
  fingerprint: string;
  scenarioId: string;
  asOf: string;
  cases: {
    id: string;
    prompt: string;
    capturedAt: string;
    seconds: number;
    text: string;
    toolsFired: string[];
    citations: { label: string; detail?: string }[];
    facts: { planned: number; delivered: number; variance: number };
    campaignIds: string[];
    dax: string;
    gql: string;
  }[];
}

export type Treatment = 'unqualified' | 'prepare-credit' | 'no-credit' | 'follow-validation' | 'review';

export interface DossierAction {
  treatment: Treatment;
  title: string;
  next: string;
  reason: string;
  unknowns: string[];
  notes: WorkNote[];
}

export function checkContractEvidence(
  item: DossierCase, evidence: { text: string; toolsFired: string[] },
): { status: 'confirmed' | 'missing' | 'contradictory'; reason: string } {
  const text = evidence.text.replace(/[*_]/g, '').replace(/\s+/g, ' ').toLowerCase();
  if (!evidence.toolsFired.some((tool) => /contract|file_search/i.test(tool))) {
    return { status: 'missing', reason: 'No contract retrieval source was reported. The treatment remains unqualified.' };
  }
  if (/(?:could not|cannot|can't|unable to|couldn't|not able to).{0,80}(?:retrieve|access|read|find|verify).{0,80}(?:agreement|contract\b)|(?:agreement|contract\b).{0,35}(?:unavailable|not available|could not be retrieved)/.test(text)) {
    return { status: 'missing', reason: 'The answer reports missing contract evidence. Review the agreement before proceeding.' };
  }
  if (item.id === 'contoso-es') {
    if (/(?:no|not entitled to (?:a )?).{0,20}(?:credit|compensation).{0,20}(?:due|required|owed)|(?:credit|compensation) (?:is |are )?(?:excluded|not due)/.test(text)) {
      return { status: 'contradictory', reason: 'The agent treatment conflicts with the prepared Contoso agreement. Human review is required.' };
    }
    if (/6\.2/.test(text) && /credit/.test(text) && /45/.test(text) && /10\s*(?:%|percent)/.test(text)) {
      return { status: 'confirmed', reason: 'Contract source and the scenario-specific clause terms were found in the response.' };
    }
  } else if (item.id === 'litware-uk') {
    if (/(?:must|shall|should) issue (?:a )?(?:compensation )?credit|requires (?:a )?(?:compensation )?credit/.test(text)) {
      return { status: 'contradictory', reason: 'The agent treatment conflicts with the prepared Litware agreement. Human review is required.' };
    }
    if (/6\.[12]/.test(text) && /no.{0,25}(?:credit|compensation)|(?:credit|compensation).{0,20}(?:excluded|not due)|not entitled/.test(text)) {
      return { status: 'confirmed', reason: 'Contract source and the scenario-specific exclusion were found in the response.' };
    }
  }
  return { status: 'missing', reason: 'The response does not establish all clause terms needed for this prepared case. Review it before using a conclusion.' };
}

export const DOSSIER_STEPS: { id: DossierStep; label: string }[] = [
  { id: 'facts', label: 'Facts' }, { id: 'contract', label: 'Contract' },
  { id: 'work', label: 'Work IQ' }, { id: 'web', label: 'Web IQ' },
  { id: 'action', label: 'Send' },
];

export function dossierStepAtLeast(step: DossierStep, minimum: DossierStep): boolean {
  return DOSSIER_STEPS.findIndex((s) => s.id === step) >= DOSSIER_STEPS.findIndex((s) => s.id === minimum);
}

function isDateKey(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

export function relevantWorkNotes(item: DossierCase, notes: WorkNote[], asOf: string) {
  return notes.filter((note) =>
    note.simulated === true && note.caseId === item.id &&
    note.advertiserId === item.advertiserId && note.marketId === item.marketId &&
    note.quarter === item.quarter && isDateKey(note.date) &&
    note.date > '2026-09-30' && note.date <= asOf);
}

/** These two reviewed demo cases are not a general-purpose legal decision engine. */
export function qualifyDossier(
  item: DossierCase, step: DossierStep, asOf: string, notes: WorkNote[], includeWork: boolean,
  contractAvailable = true,
  contractConflict = false,
  factsAvailable = true,
): DossierAction {
  const base: DossierAction = {
    treatment: 'unqualified', title: 'Treatment not yet qualified',
    next: 'Read the applicable agreement before proposing a credit.',
    reason: 'A delivery variance alone does not establish a contractual remedy.',
    unknowns: ['Contractual treatment', 'Work already underway'], notes: [],
  };
  if (!factsAvailable) return {
    ...base, title: 'Figures and scope not included',
    next: 'Include the measured figures and campaign scope before applying a contract to this delivery gap.',
    reason: 'Contract and work context alone do not establish the measured delivery variance.',
    unknowns: ['Measured variance and campaign scope', 'Treatment of this delivery gap'],
  };
  if (step === 'facts') return base;
  if (contractConflict) return { ...base, treatment: 'review', title: 'Human review needed', next: 'The agent response and the prepared contract disagree. Resolve the evidence before preparing a follow-up.' };
  if (!contractAvailable) return { ...base, next: 'The contract evidence is unavailable. Review the source before proceeding.' };
  const expectedScope = item.id === 'contoso-es' ? ['ADV-001', 'MKT-ES']
    : item.id === 'litware-uk' ? ['ADV-004', 'MKT-UK'] : null;
  if (!expectedScope || expectedScope[0] !== item.advertiserId || expectedScope[1] !== item.marketId ||
      item.quarter !== '2026-Q3' || !isDateKey(asOf) || asOf <= '2026-09-30' ||
      !Number.isFinite(item.facts.variance) || !Number.isFinite(item.facts.planned) ||
      !Number.isFinite(item.facts.delivered) || item.facts.delivered < 0 ||
      item.facts.planned <= 0 || !item.campaignIds.length ||
      Math.abs(item.facts.delivered / item.facts.planned - 1 - item.facts.variance) > 0.0005) {
    return { ...base, treatment: 'review', title: 'Evidence needs review', next: 'Confirm the completed quarter, campaign scope and measurements.' };
  }
  if (item.contract.treatment === 'excluded' && item.id === 'litware-uk' && item.facts.variance > 0 &&
      item.contract.articles.some((a) => a.number === '6.1' && a.text.trim())) {
    return {
      treatment: 'no-credit', title: 'No credit for this delivery gap',
      next: 'Do not propose a credit for this over-delivery.',
      reason: 'Articles 6.1–6.2 exclude compensation for this variance. Article 6.3 also prohibits billing the excess.',
      unknowns: ['Other account issues and work status are not established by this conclusion.'], notes: [],
    };
  }
  if (item.id !== 'contoso-es' || item.contract.treatment !== 'credit' || item.facts.variance <= 0.1 ||
      !['6.2', '6.4'].every((n) => item.contract.articles.some((a) => a.number === n && a.text.trim()))) {
    return { ...base, treatment: 'review', title: 'Review the applicable treatment', next: 'The current figures do not support the prepared scenario conclusion.' };
  }
  const action: DossierAction = {
    treatment: 'prepare-credit', title: 'Credit required under article 6.2',
    next: 'Prepare the calculation and arrange its review.',
    reason: 'Over-delivery exceeds 10% for Spain in Q3. Issue the credit within 45 days of quarter close; do not offset other markets.',
    unknowns: ['Contracted channel rates and credit amount', 'Approval and issuance', 'Work already underway'],
    notes: [],
  };
  if (!includeWork || !dossierStepAtLeast(step, 'work')) return action;
  const relevant = relevantWorkNotes(item, notes, asOf);
  if (!relevant.length) return action;
  if (relevant.some((note) => note.status !== 'prepared-awaiting-validation' || !note.nextRole.trim()) ||
      new Set(relevant.map((note) => note.nextRole)).size !== 1) {
    return {
      ...action, treatment: 'review', title: 'Human review needed',
      next: 'The work notes do not establish a consistent current status. Review them before proposing the next step.',
      notes: relevant,
    };
  }
  return {
    ...action, treatment: 'follow-validation', title: 'Follow up on validation',
    next: `Finance reports the calculation is prepared. Ask the ${relevant[0].nextRole.toLowerCase()} to confirm its review rather than requesting preparation again.`,
    unknowns: ['Contracted channel rates and credit amount', 'Approval and actual issuance'],
    notes: relevant,
  };
}

export function relevantWebNotes(item: DossierCase, context: WebContext, scenarioId: string, asOf: string): WebNote[] {
  if (!context.simulated || context.scenarioId !== scenarioId || context.asOf !== asOf || !isDateKey(asOf)) return [];
  return context.notes.filter((note) =>
    note.simulated === true && note.caseId === item.id &&
    note.advertiserId === item.advertiserId && note.marketId === item.marketId &&
    note.quarter === item.quarter && isDateKey(note.publishedOn) && note.publishedOn <= asOf);
}

export function webDraftContext(notes: WebNote[]): string {
  return notes.map((note) =>
    `Web context — ${note.source}, ${note.publishedOn}: ${note.summary} ${note.meetingPrompt}`,
  ).join('\n\n');
}

export function dossierDraft(item: DossierCase, action: DossierAction): string | null {
  if (action.treatment === 'follow-validation') {
    return `Can you confirm the review of the ${item.advertiser} ${item.market} Q3 credit calculation? Finance reports the draft is ready. Please confirm the contracted channel rates, amount and validation before issuance.`;
  }
  if (action.treatment === 'prepare-credit') {
    return `Please prepare the ${item.advertiser} ${item.market} Q3 credit calculation under article 6.2 for review. Confirm the contracted channel rates and amount before approval and issuance.`;
  }
  if (action.treatment === 'no-credit') {
    return `For ${item.advertiser} in ${item.market}, articles 6.1–6.2 exclude a credit for the Q3 over-delivery. This conclusion concerns that delivery gap only, not other account issues.`;
  }
  return null;
}

export function relevantWorkCase(item: DossierCase, context: WorkContext, scenarioId: string, asOf: string): WorkCase | null {
  if (!context.simulated || context.scenarioId !== scenarioId || context.asOf !== asOf || !isDateKey(asOf)) return null;
  const found = context.cases.find((c) =>
    c.simulated === true && c.caseId === item.id && c.advertiserId === item.advertiserId &&
    c.marketId === item.marketId && c.quarter === item.quarter);
  if (!found || !found.recipient?.name?.trim()) return null;
  const signals = found.signals.filter((s) => isDateKey(s.date) && s.date > '2026-09-30' &&
    (s.kind === 'meeting' || s.date <= asOf));
  return signals.length ? { ...found, signals } : null;
}

/** Work IQ refines who acts next once the treatment is established; it never changes the treatment. */
export function withWorkContext(action: DossierAction, work: WorkCase | null): DossierAction {
  if (!work || (action.treatment !== 'follow-validation' && action.treatment !== 'no-credit')) return action;
  return { ...action, next: work.nextStep };
}

function addDays(dateKey: string, days: number): string {
  const d = new Date(`${dateKey}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function longDate(dateKey: string): string {
  return new Date(`${dateKey}T00:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', timeZone: 'UTC' });
}

const firstName = (who: string) => who.split(' · ')[0].split(' ')[0];
const millions = (n: number) => `${(n / 1e6).toFixed(1)}M`;

/** The message sent to the person Work IQ identifies. Without Work IQ, fall back to the generic draft. */
export function dossierMessage(item: DossierCase, action: DossierAction, work: WorkCase | null,
  facts: DossierCase['facts'] = item.facts): string | null {
  if (!work || (action.treatment !== 'follow-validation' && action.treatment !== 'no-credit')) return dossierDraft(item, action);
  const hello = `Hi ${firstName(work.recipient.name)},`;
  const gap = `${item.advertiser} ${item.market} delivered ${facts.variance > 0 ? '+' : ''}${Math.round(facts.variance * 100)}% ` +
    `against the Q3 plan (${millions(facts.delivered)} vs ${millions(facts.planned)} impressions).`;
  const meeting = work.signals.find((s) => s.kind === 'meeting');
  const beforeMeeting = meeting ? ` before the ${meeting.title.split(' · ').pop()} on ${longDate(meeting.date)}` : '';
  if (action.treatment === 'follow-validation') {
    const email = work.signals.find((s) => s.kind === 'email');
    const file = work.signals.find((s) => s.kind === 'file');
    const preparer = email ? firstName(email.who) : 'Finance';
    return `${hello} ${gap} Under article 6.2 of ${item.contract.reference}, a make-good credit is due and must be issued ` +
      `by ${longDate(addDays('2026-09-30', 45))}, without ${item.advertiser.split(' ')[0]} having to ask. ` +
      `${preparer} has already prepared the calculation${file ? ` (${file.title})` : ''} and is waiting for your validation. ` +
      `Could you review it${beforeMeeting}? Please confirm the contracted channel rates and the amount before issuance.`;
  }
  const chat = work.signals.find((s) => s.kind === 'teams');
  const client = chat ? `${firstName(chat.who)}'s carry-over request from ${longDate(chat.date)}` : 'the client\'s question';
  return `${hello} on ${client}: ${gap} Articles 6.1–6.2 of ${item.contract.reference} rule out any credit or carry-over ` +
    `for over-delivery, whatever its size. Under article 6.3 we invoice the approved budget only, never the extra volume, ` +
    `so the Q3 invoice on hold can be released on that basis. Worth closing${beforeMeeting}.`;
}

export function dossierPrompt(item: DossierCase, asOf: string): string {
  return `Review the fictional Zava demo at the scenario date ${asOf}, after 2026-Q3 has closed. ` +
    `For ${item.advertiser} (${item.advertiserId}) in ${item.market} (${item.marketId}) during ${item.quarter}, ` +
    `read [Planned Impressions], [Delivered Impressions] and [Delivery vs Plan %] from the semantic model. ` +
    `Verify the campaign scope using the published relationships; expected candidate IDs to check are ${item.campaignIds.join(', ')}. ` +
    `Retrieve the signed master agreement, cite the applicable delivery-variance articles and their assessment period. ` +
    `Explain the treatment supported by those sources. Do not infer a monetary credit amount without verified contracted channel rates. ` +
    `Do not assume an approval, issuance or any work progress; no collaboration system is connected for this question. ` +
    `Say explicitly if evidence is missing or disagrees with the candidate scope. Use the data and contracts tools.`;
}
