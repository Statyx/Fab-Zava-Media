import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import App from '@/App';
import { QuerySourceContext } from '@/data/querySource';
import { IqInPracticePage } from '@/pages/IqInPracticePage';
import { dossierDraft, dossierMessage, dossierPrompt, qualifyDossier, relevantWebNotes, relevantWorkCase, webDraftContext, withWorkContext, type DossierCapture, type DossierCase } from '@/domain/dossier';
import { DOSSIER_REFERENCE, DOSSIER_WEB_CONTEXT, DOSSIER_WORK_CONTEXT, graphCampaignIds, readLiveDossier, recordedDossiers, validateCapture } from '@/services/dossier';

const stage = vi.hoisted(() => ({ STAGE_MS: 0, SEND_MS: 0 }));
vi.mock('@/services/stage', () => ({
  get STAGE_MS() { return stage.STAGE_MS; },
  get SEND_MS() { return stage.SEND_MS; },
}));
const auth = vi.hoisted(() => ({ isAuthenticated: true, loading: false, user: null, signOut: vi.fn() }));
vi.mock('@/hooks/AuthContext', () => ({ useAuth: () => auth }));
vi.mock('@/services/dossier', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/dossier')>();
  return { ...actual, recordedDossiers: vi.fn(), readLiveDossier: vi.fn() };
});
vi.mock('@/services/dataAgent', () => ({
  askDataAgent: vi.fn(), dataAgentConfigured: () => true,
  DataAgentNotConfiguredError: class extends Error {},
}));
vi.mock('@/services/foundryAgent', () => ({
  askSupervisor: vi.fn(), supervisorConfigured: () => true,
  SupervisorNotConfiguredError: class extends Error {},
}));
vi.mock('@/services/powerbi', () => ({
  executeDax: vi.fn().mockRejectedValue(new Error('Unexpected live query')),
  semanticModelId: 'test-model', powerbiConfigured: true,
}));

const [contoso, litware] = DOSSIER_REFERENCE.cases;
const notes = DOSSIER_REFERENCE.workNotes;
const asOf = DOSSIER_REFERENCE.asOf;
const webFor = (item: DossierCase) => relevantWebNotes(item, DOSSIER_WEB_CONTEXT, DOSSIER_REFERENCE.scenarioId, asOf);
const workFor = (item: DossierCase) => relevantWorkCase(item, DOSSIER_WORK_CONTEXT, DOSSIER_REFERENCE.scenarioId, asOf);
function messageFor(item: DossierCase, includeWork: boolean) {
  const work = includeWork ? workFor(item) : null;
  return dossierMessage(item, withWorkContext(qualifyDossier(item, 'action', asOf, notes, includeWork), work), work);
}
const capture: DossierCapture = {
  fingerprint: DOSSIER_REFERENCE.fingerprint, scenarioId: DOSSIER_REFERENCE.scenarioId, asOf,
  cases: DOSSIER_REFERENCE.cases.map((item) => ({
    id: item.id, prompt: dossierPrompt(item, asOf), capturedAt: '2026-09-15T12:00:00Z',
    seconds: 75, text: item.id === 'contoso-es'
      ? 'Test-only response: Contoso article 6.2 requires a compensation credit above 10%, within 45 days.'
      : 'Test-only response: Litware articles 6.1–6.2 provide no compensation and no credit for this variance.',
    toolsFired: ['contract-tool'], citations: [], facts: item.facts, campaignIds: item.campaignIds,
    dax: 'EVALUATE test', gql: 'MATCH test',
  })),
};

beforeEach(() => {
  stage.STAGE_MS = 0;
  stage.SEND_MS = 0;
  auth.isAuthenticated = true;
  vi.clearAllMocks();
  vi.mocked(recordedDossiers).mockReturnValue({ capture: null, error: 'No compatible recording.' });
});
afterEach(() => vi.useRealTimers());

function mount(preview = true) {
  return render(<MemoryRouter><QuerySourceContext.Provider value={{ preview, execute: vi.fn() }}>
    <IqInPracticePage />
  </QuerySourceContext.Provider></MemoryRouter>);
}

async function openDraft(user = userEvent.setup()) {
  await user.click(screen.getByRole('button', { name: '4 Web IQ' }));
  await user.click(screen.getByRole('button', { name: /Find who to tell/ }));
}

describe('dossier qualification', () => {
  it('does not infer a credit from facts alone', () => {
    for (const item of [contoso, litware]) {
      const action = qualifyDossier(item, 'facts', asOf, notes, false);
      expect(action.treatment).toBe('unqualified');
      expect(dossierDraft(item, action)).toBeNull();
    }
  });
  it('qualifies similar gaps differently using the applicable agreement', () => {
    expect(qualifyDossier(contoso, 'contract', asOf, notes, false).treatment).toBe('prepare-credit');
    const result = qualifyDossier(litware, 'contract', asOf, notes, false);
    expect(result.treatment).toBe('no-credit');
    expect(result.reason).toContain('6.1–6.2');
    expect(result.unknowns.join(' ')).toContain('Other account issues');
  });
  it('changes the next step, never the obligation, after the simulated note', () => {
    const result = qualifyDossier(contoso, 'work', asOf, notes, true);
    expect(result.treatment).toBe('follow-validation');
    expect(result.unknowns.join(' ')).toContain('actual issuance');
    expect(dossierDraft(contoso, result)).toContain('confirm');
    expect(qualifyDossier(contoso, 'work', asOf, notes, false).treatment).toBe('prepare-credit');
    expect(qualifyDossier(contoso, 'web', asOf, notes, true)).toEqual(result);
  });
  it('does not substitute irrelevant, future or non-simulated notes', () => {
    for (const altered of [
      { ...notes[0], marketId: 'MKT-UK' }, { ...notes[0], quarter: '2026-Q2' },
      { ...notes[0], date: '2026-11-01' }, { ...notes[0], simulated: false },
      { ...notes[0], date: '2026-10-00' },
    ]) {
      expect(qualifyDossier(contoso, 'work', asOf, [altered], true).treatment).toBe('prepare-credit');
    }
  });
  it('keeps incomplete or conflicting evidence open for review', () => {
    expect(qualifyDossier(contoso, 'contract', asOf, [], false, false).treatment).toBe('unqualified');
    expect(qualifyDossier(contoso, 'contract', '2026-09-15', [], false).treatment).toBe('review');
    expect(qualifyDossier({ ...contoso, campaignIds: [] }, 'contract', asOf, [], false).treatment).toBe('review');
    expect(qualifyDossier({ ...contoso, marketId: 'MKT-FR' }, 'contract', asOf, [], false).treatment).toBe('review');
    expect(qualifyDossier({ ...contoso, contract: { ...contoso.contract, articles: [] } }, 'contract', asOf, [], false).treatment).toBe('review');
    const result = qualifyDossier(contoso, 'work', asOf, [...notes, { ...notes[0], id: 'contradiction', status: 'issued' }], true);
    expect(result.treatment).toBe('review');
    expect(result.notes).toHaveLength(2);
    expect(dossierDraft(contoso, result)).toBeNull();
  });
});

describe('recording validation', () => {
  it('requires matching inputs, prompt, measurements and membership', () => {
    expect(validateCapture(capture).cases).toHaveLength(2);
    expect(() => validateCapture({ ...capture, fingerprint: 'old' })).toThrow(/fingerprint/);
    expect(() => validateCapture({ ...capture, cases: [] })).toThrow(/not available/);
    const [entry] = capture.cases;
    expect(() => validateCapture({ ...capture, cases: [{ ...entry, campaignIds: ['wrong'] }, capture.cases[1]] })).toThrow(/scope differ/);
    expect(() => validateCapture({ ...capture, cases: [{ ...entry, prompt: 'different' }, capture.cases[1]] })).toThrow(/not available/);
    expect(() => validateCapture({ ...capture, cases: [{ ...entry, toolsFired: [] }, capture.cases[1]] })).toThrow(/not available/);
    expect(() => validateCapture({ ...capture, cases: [{ ...entry, text: 'I could not retrieve the signed agreement.' }, capture.cases[1]] })).toThrow(/missing contract/);
    expect(() => validateCapture({ ...capture, cases: [{ ...entry, text: 'Under article 6.2, no credit is due for Contoso.' }, capture.cases[1]] })).toThrow(/conflicts/);
  });
  it('rejects HTTP-success-shaped graph failures and missing keys', () => {
    expect(() => graphCampaignIds({ status: { code: 'error' }, result: { kind: 'TABLE', data: [] } })).toThrow();
    expect(() => graphCampaignIds({ status: { code: '00000' }, result: { kind: 'TABLE', data: [{}] } })).toThrow(/identifier/);
    expect(graphCampaignIds({ status: { code: '00000' }, result: { kind: 'TABLE', data: [{ campaignId: 'c' }, { campaignId: 'c' }] } })).toEqual(['c']);
  });
});

describe('fictional web context', () => {
  it('matches each notice to its account, market, quarter and scenario date', () => {
    expect(webFor(contoso)).toHaveLength(1);
    expect(webFor(litware)).toHaveLength(1);
    expect(webFor(contoso)[0].id).not.toBe(webFor(litware)[0].id);
    const [note] = webFor(contoso);
    for (const altered of [
      { ...note, caseId: litware.id }, { ...note, advertiserId: litware.advertiserId },
      { ...note, marketId: 'MKT-UK' }, { ...note, quarter: '2026-Q2' },
      { ...note, publishedOn: '2026-10-16' }, { ...note, publishedOn: '2026-02-30' },
      { ...note, simulated: false },
    ]) {
      expect(relevantWebNotes(contoso, { ...DOSSIER_WEB_CONTEXT, notes: [altered] }, DOSSIER_REFERENCE.scenarioId, asOf)).toEqual([]);
    }
    expect(relevantWebNotes(contoso, DOSSIER_WEB_CONTEXT, 'wrong-scenario', asOf)).toEqual([]);
    expect(relevantWebNotes(contoso, DOSSIER_WEB_CONTEXT, DOSSIER_REFERENCE.scenarioId, '2026-10-14')).toEqual([]);
    expect(relevantWebNotes(contoso, { ...DOSSIER_WEB_CONTEXT, simulated: false }, DOSSIER_REFERENCE.scenarioId, asOf)).toEqual([]);
  });
  it('keeps simulated web notices out of the actual Fabric/Foundry capture and prompt', () => {
    expect(validateCapture(capture).cases).toHaveLength(2);
    for (const item of DOSSIER_REFERENCE.cases) {
      const prompt = dossierPrompt(item, asOf);
      for (const note of DOSSIER_WEB_CONTEXT.notes) {
        expect(prompt).not.toContain(note.headline);
        expect(prompt).not.toContain(note.summary);
      }
    }
    expect(webDraftContext([])).toBe('');
  });
});

describe('dossier storyboard', () => {
  it('opens straight on the example, without an evidence-mode selector or demo disclaimers', () => {
    mount();
    expect(screen.queryByLabelText('Evidence mode')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Read live' })).not.toBeInTheDocument();
    expect(screen.queryByText(/not live|Repository example|Recorded evidence/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Read the contracts/ })).toBeEnabled();
    expect(readLiveDossier).not.toHaveBeenCalled();
  });
  it('does not label the storyline as simulated or fictional', async () => {
    stage.SEND_MS = 0;
    mount();
    await openDraft();
    fireEvent.click(within(screen.getByRole('article', { name: 'Contoso Mobility dossier' })).getByRole('button', { name: 'Send in Teams' }));
    expect(document.body.textContent).not.toMatch(/simulated|fictional|fictitious|not live/i);
  });
  it('walks through the two treatments, work context, message and reset', async () => {
    mount();
    const user = userEvent.setup();
    const c = () => screen.getByRole('article', { name: 'Contoso Mobility dossier' });
    const l = () => screen.getByRole('article', { name: 'Litware Retail dossier' });
    expect(within(c()).getByText('Treatment not yet qualified')).toBeVisible();
    await user.click(screen.getByRole('button', { name: /Read the contracts/ }));
    expect(within(c()).getByText('Credit required under article 6.2')).toBeVisible();
    expect(within(l()).getByText('No credit for this delivery gap')).toBeVisible();
    await user.click(screen.getByRole('button', { name: /Add Work IQ/ }));
    expect(within(c()).getByText('Follow up on validation')).toBeVisible();
    expect(within(c()).getByRole('list', { name: 'Contoso Mobility Work IQ signals' })).toBeVisible();
    expect(screen.getByRole('button', { name: '5 Send' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Include Web IQ context' })).toBeDisabled();
    expect(screen.queryByText(webFor(contoso)[0].headline)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Add Web IQ/ }));
    expect(screen.getByRole('button', { name: '4 Web IQ' })).toHaveAttribute('aria-current', 'step');
    expect(within(c()).getByText('Follow up on validation')).toBeVisible();
    expect(within(c()).getByText(webFor(contoso)[0].headline)).toBeVisible();
    expect(within(l()).getByText(webFor(litware)[0].headline)).toBeVisible();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Find who to tell/ }));
    expect(screen.getByRole('textbox', { name: 'Contoso Mobility message' })).toHaveValue(
      `${messageFor(contoso, true)}\n\n${webDraftContext(webFor(contoso))}`,
    );
    await user.click(screen.getByRole('checkbox', { name: 'Include Work IQ context' }));
    expect(screen.getByRole('textbox', { name: 'Contoso Mobility message' })).toHaveValue(
      `${messageFor(contoso, false)}\n\n${webDraftContext(webFor(contoso))}`,
    );
    await user.click(screen.getByRole('button', { name: 'Reset' }));
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '5 Send' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Include Web IQ context' })).toBeDisabled();
    expect(readLiveDossier).not.toHaveBeenCalled();
  });
  it('reveals verbatim contracts and the scoped campaign IDs on demand', async () => {
    mount();
    fireEvent.click(screen.getByRole('button', { name: /Read the contracts/ }));
    const c = screen.getByRole('article', { name: 'Contoso Mobility dossier' });
    fireEvent.click(within(c).getByRole('button', { name: 'Contract articles' }));
    expect(within(c).getByText(/Verbatim excerpts/)).toBeVisible();
    expect(within(within(c).getByRole('region', { name: 'Contoso Mobility contract evidence' }))
      .getByText(/compensation credit/)).toBeVisible();
    fireEvent.click(within(c).getByRole('button', { name: 'Why this scope?' }));
    for (const id of contoso.campaignIds) expect(within(c).getByText(id)).toBeVisible();
  });
  it('does not claim copying succeeded if clipboard access fails', async () => {
    mount();
    const user = userEvent.setup();
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockRejectedValue(new Error('Denied')) } });
    await openDraft(user);
    const c = screen.getByRole('article', { name: 'Contoso Mobility dossier' });
    await user.click(within(c).getByRole('button', { name: 'Copy message' }));
    expect(await within(c).findByRole('alert')).toHaveTextContent('Clipboard access failed');
    expect(within(c).queryByText('Copied.')).not.toBeInTheDocument();
  });
  it('shows the contribution of Fabric and Foundry by withholding both drafts when either is excluded', async () => {
    mount();
    const user = userEvent.setup();
    await openDraft(user);
    expect(screen.getAllByRole('textbox')).toHaveLength(2);
    await user.click(screen.getByRole('checkbox', { name: 'Include Fabric IQ context' }));
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.getAllByText('Figures and scope not included').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByRole('button', { name: 'Figures' }).every((button) => button.hasAttribute('disabled'))).toBe(true);
    await user.click(screen.getByRole('checkbox', { name: 'Include Fabric IQ context' }));
    expect(screen.getAllByRole('textbox')).toHaveLength(2);
    await user.click(screen.getByRole('checkbox', { name: 'Include Foundry context' }));
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByText('No credit for this delivery gap')).not.toBeInTheDocument();
    expect(screen.getAllByText('Treatment not yet qualified')).toHaveLength(2);
    await user.click(screen.getByRole('checkbox', { name: 'Include Foundry context' }));
    expect(screen.getAllByRole('textbox')).toHaveLength(2);
    expect(readLiveDossier).not.toHaveBeenCalled();
  });
  it('keeps a Work IQ exclusion when moving from work context to the final draft', async () => {
    mount();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '3 Work IQ' }));
    await user.click(screen.getByRole('checkbox', { name: 'Include Work IQ context' }));
    await user.click(screen.getByRole('button', { name: /Add Web IQ/ }));
    expect(screen.getByRole('checkbox', { name: 'Include Work IQ context' })).not.toBeChecked();
    await user.click(screen.getByRole('checkbox', { name: 'Include Web IQ context' }));
    await user.click(screen.getByRole('button', { name: /Find who to tell/ }));
    expect(screen.getByRole('checkbox', { name: 'Include Work IQ context' })).not.toBeChecked();
    expect(screen.getByRole('textbox', { name: 'Contoso Mobility message' })).toHaveValue(
      messageFor(contoso, false),
    );
  });
  it('adds Web IQ announcements and their source labels to each draft without changing treatment', async () => {
    mount();
    const user = userEvent.setup();
    await openDraft(user);
    for (const item of DOSSIER_REFERENCE.cases) {
      const card = screen.getByRole('article', { name: `${item.advertiser} dossier` });
      const note = webFor(item)[0];
      expect(within(card).getByText(note.headline)).toBeVisible();
      const draft = within(card).getByRole('textbox');
      expect(draft).toHaveTextContent(`Web context — ${note.source}, ${note.publishedOn}`);
      expect(draft).toHaveTextContent(note.summary);
      expect(draft).toHaveTextContent(note.meetingPrompt);
      expect(within(card).queryByRole('link')).not.toBeInTheDocument();
      expect(card.lastElementChild).toHaveClass('dossier-draft');
    }
    expect(screen.getByText('Follow up on validation')).toBeVisible();
    expect(screen.getByText('No credit for this delivery gap')).toBeVisible();
    await user.click(screen.getByRole('checkbox', { name: 'Include Web IQ context' }));
    expect(screen.getAllByText('Web context is not included. No public announcement will be added to the message.')).toHaveLength(2);
    for (const note of DOSSIER_WEB_CONTEXT.notes) expect(screen.queryByText(note.headline)).not.toBeInTheDocument();
    for (const item of DOSSIER_REFERENCE.cases) {
      expect(screen.getByRole('textbox', { name: `${item.advertiser} message` })).toHaveValue(
        messageFor(item, true),
      );
    }
    expect(readLiveDossier).not.toHaveBeenCalled();
  });
  it('requires the Web IQ stage before the draft and preserves its choice across backward navigation', async () => {
    mount();
    const user = userEvent.setup();
    const navigation = screen.getByRole('navigation', { name: 'Dossier context' });
    expect(within(navigation).getAllByRole('button').map((button) => button.textContent))
      .toEqual(['1Facts', '2Contract', '3Work IQ', '4Web IQ', '5Send']);
    fireEvent.click(screen.getByRole('button', { name: '5 Send' }));
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '1 Facts' })).toHaveAttribute('aria-current', 'step');
    await user.click(screen.getByRole('button', { name: '4 Web IQ' }));
    await user.click(screen.getByRole('checkbox', { name: 'Include Web IQ context' }));
    await user.click(screen.getByRole('button', { name: '3 Work IQ' }));
    expect(screen.getByRole('checkbox', { name: 'Include Web IQ context' })).toBeDisabled();
    expect(screen.queryByText(webFor(contoso)[0].headline)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Add Web IQ/ }));
    expect(screen.getByRole('checkbox', { name: 'Include Web IQ context' })).not.toBeChecked();
    await user.click(screen.getByRole('button', { name: /Find who to tell/ }));
    expect(screen.getByRole('textbox', { name: 'Contoso Mobility message' })).toHaveValue(
      messageFor(contoso, true),
    );
    await user.click(screen.getByRole('button', { name: 'Reset' }));
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '5 Send' })).toBeDisabled();
    expect(readLiveDossier).not.toHaveBeenCalled();
  });
  it('marks each added layer with a two-second pause, and goes back immediately', async () => {
    stage.STAGE_MS = 2000;
    vi.useFakeTimers();
    mount();
    fireEvent.click(screen.getByRole('button', { name: /Read the contracts/ }));
    expect(screen.getByRole('status')).toHaveTextContent('Foundry agents are reading the two agreements…');
    expect(screen.getByRole('button', { name: /Working…/ })).toBeDisabled();
    expect(document.querySelector('.dossier-cards')).toHaveAttribute('aria-busy', 'true');
    await act(async () => { await vi.advanceTimersByTimeAsync(1999); });
    expect(screen.queryByText('Credit required under article 6.2')).not.toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(screen.getByText('Credit required under article 6.2')).toBeVisible();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Add Work IQ/ }));
    expect(screen.getByRole('status')).toHaveTextContent('Work IQ is searching mail, Teams chats, meetings and files…');
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.getByText('Follow up on validation')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: '2 Contract' }));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.getByText('Credit required under article 6.2')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: /Add Work IQ/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.getByRole('button', { name: '1 Facts' })).toHaveAttribute('aria-current', 'step');
    expect(screen.queryByText('Follow up on validation')).not.toBeInTheDocument();
  });
  it('shows the Work IQ signals, people and what they change', async () => {
    mount();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '3 Work IQ' }));
    for (const item of DOSSIER_REFERENCE.cases) {
      const work = workFor(item)!;
      const card = screen.getByRole('article', { name: `${item.advertiser} dossier` });
      const signals = within(card).getByRole('list', { name: `${item.advertiser} Work IQ signals` });
      expect(within(signals).getAllByRole('listitem')).toHaveLength(work.signals.length);
      for (const signal of work.signals) expect(within(signals).getByText(signal.title)).toBeVisible();
      expect(within(card).getByText(work.impact)).toBeVisible();
      expect(within(card).getByText(work.nextStep)).toBeVisible();
    }
    expect(screen.getByText('Outlook · email · 2026-10-12')).toBeVisible();
    expect(screen.getByText('Teams · chat · 2026-10-09')).toBeVisible();
    await user.click(screen.getByRole('checkbox', { name: 'Include Work IQ context' }));
    expect(screen.queryByRole('list', { name: /Work IQ signals/ })).not.toBeInTheDocument();
    expect(screen.getAllByText('Work context is not included. What is already underway, and who owns it, is unknown.')).toHaveLength(2);
  });
  it('sends each message to the person Work IQ found', async () => {
    stage.SEND_MS = 2000;
    mount();
    const user = userEvent.setup();
    await openDraft(user);
    const c = screen.getByRole('article', { name: 'Contoso Mobility dossier' });
    const l = screen.getByRole('article', { name: 'Litware Retail dossier' });
    expect(within(c).getByRole('list', { name: 'Why Elena Ruiz' })).toBeVisible();
    expect(within(l).getByRole('list', { name: 'Why James Carter' })).toBeVisible();
    for (const reason of workFor(contoso)!.recipient.reasons) expect(within(c).getByText(reason)).toBeVisible();
    expect(within(c).getByText('Found by Work IQ')).toBeVisible();
    const contosoMessage = within(c).getByRole('textbox', { name: 'Contoso Mobility message' });
    expect(contosoMessage).toHaveValue(`${messageFor(contoso, true)}\n\n${webDraftContext(webFor(contoso))}`);
    expect(contosoMessage).toHaveTextContent('Hi Elena,');
    expect(contosoMessage).toHaveTextContent('by 14 November');
    expect(contosoMessage).toHaveTextContent('Contoso_ES_Q3_make-good.xlsx');
    expect(contosoMessage).toHaveTextContent('before the Q3 business review on 21 October');
    const litwareMessage = within(l).getByRole('textbox', { name: 'Litware Retail message' });
    expect(litwareMessage).toHaveTextContent("Hi James, on Sarah's carry-over request from 9 October");
    expect(litwareMessage).toHaveTextContent('article 6.3');
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.click(within(c).getByRole('button', { name: 'Send in Teams' }));
    expect(within(c).getByRole('button', { name: /Sending…/ })).toBeDisabled();
    expect(within(c).queryByText(/Sent to Elena Ruiz/)).not.toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(within(c).getByRole('status')).toHaveTextContent('Sent to Elena Ruiz in Teams.');
    expect(within(c).getByRole('button', { name: 'Sent' })).toBeDisabled();
    expect(within(l).getByRole('button', { name: 'Send in Teams' })).toBeEnabled();
    vi.useRealTimers();
    await user.click(screen.getByRole('checkbox', { name: 'Include Work IQ context' }));
    for (const card of [screen.getByRole('article', { name: 'Contoso Mobility dossier' }), screen.getByRole('article', { name: 'Litware Retail dossier' })]) {
      expect(within(card).getByText('Recipient unknown. Include Work IQ to find who owns the next step.')).toBeVisible();
      expect(within(card).getByRole('button', { name: 'Send in Teams' })).toBeDisabled();
    }
    expect(readLiveDossier).not.toHaveBeenCalled();
  });
});

describe('Work IQ context', () => {
  it('lets Work IQ change who acts and how, never the contractual treatment', () => {
    for (const item of DOSSIER_REFERENCE.cases) {
      const base = qualifyDossier(item, 'action', asOf, notes, true);
      const refined = withWorkContext(base, workFor(item));
      expect(refined.treatment).toBe(base.treatment);
      expect(refined.title).toBe(base.title);
      expect(refined.next).toBe(workFor(item)!.nextStep);
    }
    const undetermined = qualifyDossier(contoso, 'action', asOf, notes, true, false);
    expect(withWorkContext(undetermined, workFor(contoso))).toEqual(undetermined);
    expect(dossierMessage(contoso, undetermined, workFor(contoso))).toBeNull();
    expect(relevantWorkCase(contoso, DOSSIER_WORK_CONTEXT, 'other-scenario', asOf)).toBeNull();
    expect(relevantWorkCase(contoso, DOSSIER_WORK_CONTEXT, DOSSIER_REFERENCE.scenarioId, '2026-10-16')).toBeNull();
    expect(relevantWorkCase(contoso, { ...DOSSIER_WORK_CONTEXT, simulated: false }, DOSSIER_REFERENCE.scenarioId, asOf)).toBeNull();
    expect(relevantWorkCase({ ...contoso, marketId: 'MKT-FR' }, DOSSIER_WORK_CONTEXT, DOSSIER_REFERENCE.scenarioId, asOf)).toBeNull();
  });
});

describe('dossier navigation', () => {
  it.each(['/preview/iq-in-practice', '/preview/iq-in-practice/', '/iq-in-practice/'])(
    'preserves provenance and full-width layout on %s',
    async (path) => {
      window.history.replaceState({}, '', path);
      render(<App />);
      await screen.findByRole('heading', { level: 1, name: 'Which delivery gaps need action?' }, { timeout: 5000 });
      expect(screen.getByText('IQ walkthrough')).toBeVisible();
      expect(screen.queryByText('Live Fabric data')).not.toBeInTheDocument();
      expect(screen.queryByRole('textbox', { name: 'Ask the Zava assistant a question' })).not.toBeInTheDocument();
    },
  );
  it('keeps the real route behind authentication', () => {
    auth.isAuthenticated = false;
    window.history.replaceState({}, '', '/iq-in-practice');
    render(<App />);
    expect(window.location.pathname).toBe('/auth');
  });
});
