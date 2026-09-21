import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import App from '@/App';
import { QuerySourceContext } from '@/data/querySource';
import { IqInPracticePage } from '@/pages/IqInPracticePage';
import { dossierDraft, dossierPrompt, qualifyDossier, relevantWebNotes, webDraftContext, type DossierCapture, type DossierCase } from '@/domain/dossier';
import { DOSSIER_REFERENCE, DOSSIER_WEB_CONTEXT, graphCampaignIds, readLiveDossier, recordedDossiers, validateCapture } from '@/services/dossier';

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
  await user.click(screen.getByRole('button', { name: /Prepare the draft/ }));
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
  it('opens directly in the labelled demo when recordings are unavailable, without a mode gate', () => {
    mount();
    expect(screen.getByText('Repository example · not live')).toBeVisible();
    expect(screen.queryByText('Recorded evidence is not available yet.')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Explore repository example' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Review the context/ })).toBeEnabled();
    expect(readLiveDossier).not.toHaveBeenCalled();
  });
  it('keeps a manually selected unavailable recording explicit rather than silently substituting data', () => {
    mount();
    fireEvent.change(screen.getByLabelText('Evidence mode'), { target: { value: 'recorded' } });
    expect(screen.getByText('Recorded evidence is not available yet.')).toBeVisible();
    expect(screen.getByRole('button', { name: /Review the context/ })).toBeDisabled();
    expect(readLiveDossier).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Explore repository example' }));
    expect(screen.getByText('Repository example · not live')).toBeVisible();
    expect(screen.getByRole('button', { name: /Review the context/ })).toBeEnabled();
  });
  it('walks through the two treatments, simulated progress, draft and reset', async () => {
    mount();
    const user = userEvent.setup();
    const c = () => screen.getByRole('article', { name: 'Contoso Mobility dossier' });
    const l = () => screen.getByRole('article', { name: 'Litware Retail dossier' });
    expect(within(c()).getByText('Treatment not yet qualified')).toBeVisible();
    await user.click(screen.getByRole('button', { name: /Review the context/ }));
    expect(within(c()).getByText('Credit required under article 6.2')).toBeVisible();
    expect(within(l()).getByText('No credit for this delivery gap')).toBeVisible();
    await user.click(screen.getByRole('button', { name: /Add work context/ }));
    expect(within(c()).getByText('Follow up on validation')).toBeVisible();
    expect(within(c()).getByText('Work IQ — simulated')).toBeVisible();
    expect(screen.getByRole('button', { name: '5 Draft' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Include Web IQ context' })).toBeDisabled();
    expect(screen.queryByText('Web IQ — simulated')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Review web context/ }));
    expect(screen.getByRole('button', { name: '4 Web IQ' })).toHaveAttribute('aria-current', 'step');
    expect(within(c()).getByText('Follow up on validation')).toBeVisible();
    expect(within(c()).getByText(webFor(contoso)[0].headline)).toBeVisible();
    expect(within(l()).getByText(webFor(litware)[0].headline)).toBeVisible();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Prepare the draft/ }));
    expect(screen.getByRole('textbox', { name: 'Contoso Mobility follow-up draft' })).toHaveValue(
      `${dossierDraft(contoso, qualifyDossier(contoso, 'action', asOf, notes, true))}\n\n${webDraftContext(webFor(contoso))}`,
    );
    await user.click(screen.getByRole('checkbox', { name: /Include simulated/ }));
    expect(screen.getByRole('textbox', { name: 'Contoso Mobility follow-up draft' })).toHaveValue(
      `${dossierDraft(contoso, qualifyDossier(contoso, 'action', asOf, notes, false))}\n\n${webDraftContext(webFor(contoso))}`,
    );
    await user.click(screen.getByRole('button', { name: 'Reset' }));
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '5 Draft' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Include Web IQ context' })).toBeDisabled();
    expect(readLiveDossier).not.toHaveBeenCalled();
  });
  it('reveals verbatim contracts and the scoped campaign IDs on demand', async () => {
    mount();
    fireEvent.click(screen.getByRole('button', { name: /Review the context/ }));
    const c = screen.getByRole('article', { name: 'Contoso Mobility dossier' });
    fireEvent.click(within(c).getByRole('button', { name: 'Contract articles' }));
    expect(within(c).getByText(/Verbatim excerpts/)).toBeVisible();
    expect(within(within(c).getByRole('region', { name: 'Contoso Mobility contract evidence' }))
      .getByText(/compensation credit/)).toBeVisible();
    fireEvent.click(within(c).getByRole('button', { name: 'Why this scope?' }));
    for (const id of contoso.campaignIds) expect(within(c).getByText(id)).toBeVisible();
  });
  it('discloses the five-second replay and cancels it on reset', async () => {
    vi.useFakeTimers();
    vi.mocked(recordedDossiers).mockReturnValue({ capture, error: null });
    mount();
    fireEvent.click(within(screen.getByRole('article', { name: 'Contoso Mobility dossier' })).getByRole('button', { name: 'All evidence' }));
    expect(screen.queryByText(capture.cases[0].text)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Review the context/ }));
    fireEvent.click(within(screen.getByRole('article', { name: 'Contoso Mobility dossier' })).getByRole('button', { name: 'All evidence' }));
    expect(screen.queryByText(capture.cases[0].text)).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Replaying recorded evidence');
    await act(async () => { await vi.advanceTimersByTimeAsync(4999); });
    expect(screen.queryByText('Credit required under article 6.2')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(screen.queryByText('Credit required under article 6.2')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Review the context/ }));
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(screen.getByText('Credit required under article 6.2')).toBeVisible();
    expect(readLiveDossier).not.toHaveBeenCalled();
  });
  it('keeps live failures visible rather than silently substituting a recording', async () => {
    vi.mocked(recordedDossiers).mockReturnValue({ capture, error: null });
    vi.mocked(readLiveDossier).mockRejectedValueOnce(new Error('Graph scope mismatch'));
    mount(false);
    await userEvent.click(screen.getByRole('button', { name: 'Read live' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Graph scope mismatch');
    expect(screen.queryByText('Credit required under article 6.2')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Use recorded evidence' })).toBeVisible();
  });
  it('discards a late live response when the evidence mode changes', async () => {
    let finish!: (value: DossierCapture['cases'][number]) => void;
    vi.mocked(readLiveDossier).mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    mount(false);
    await userEvent.click(screen.getByRole('button', { name: 'Read live' }));
    await userEvent.selectOptions(screen.getByLabelText('Evidence mode'), 'repository');
    await act(async () => { finish(capture.cases[0]); });
    expect(screen.getByText('Repository example · not live')).toBeVisible();
    expect(screen.queryByText('Credit required under article 6.2')).not.toBeInTheDocument();
    expect(readLiveDossier).toHaveBeenCalledTimes(1);
  });
  it('does a fresh read each time the explicit Read live button is clicked', async () => {
    vi.mocked(readLiveDossier).mockImplementation(async (item) => capture.cases.find((c) => c.id === item.id)!);
    mount(false);
    await userEvent.click(screen.getByRole('button', { name: 'Read live' }));
    expect(await screen.findByText('Credit required under article 6.2')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Read live' }));
    expect(await screen.findByText('Credit required under article 6.2')).toBeVisible();
    expect(readLiveDossier).toHaveBeenCalledTimes(4);
  });
  it('does not turn a sourced data answer with missing agreement into a contractual action', async () => {
    vi.mocked(readLiveDossier).mockImplementation(async (item) => ({
      ...capture.cases.find((c) => c.id === item.id)!,
      text: 'I could not retrieve the signed agreement.',
      toolsFired: ['fabricdataagent'],
    }));
    mount(false);
    await userEvent.click(screen.getByRole('button', { name: 'Read live' }));
    expect(await screen.findAllByRole('alert')).toHaveLength(2);
    expect(screen.queryByText('Credit required under article 6.2')).not.toBeInTheDocument();
    await openDraft();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });
  it('does not claim copying succeeded if clipboard access fails', async () => {
    mount();
    const user = userEvent.setup();
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockRejectedValue(new Error('Denied')) } });
    await openDraft(user);
    const c = screen.getByRole('article', { name: 'Contoso Mobility dossier' });
    await user.click(within(c).getByRole('button', { name: 'Copy draft' }));
    expect(await within(c).findByRole('alert')).toHaveTextContent('Clipboard access failed');
    expect(within(c).queryByText('Copied. Nothing has been sent.')).not.toBeInTheDocument();
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
    await user.click(screen.getByRole('checkbox', { name: /Include simulated Work IQ/ }));
    await user.click(screen.getByRole('button', { name: /Review web context/ }));
    expect(screen.getByRole('checkbox', { name: /Include simulated Work IQ/ })).not.toBeChecked();
    await user.click(screen.getByRole('checkbox', { name: 'Include Web IQ context' }));
    await user.click(screen.getByRole('button', { name: /Prepare the draft/ }));
    expect(screen.getByRole('checkbox', { name: /Include simulated Work IQ/ })).not.toBeChecked();
    expect(screen.getByRole('textbox', { name: 'Contoso Mobility follow-up draft' })).toHaveValue(
      dossierDraft(contoso, qualifyDossier(contoso, 'action', asOf, notes, false)),
    );
  });
  it('adds fictional Web IQ notices and their source labels to each draft without changing treatment', async () => {
    mount();
    const user = userEvent.setup();
    await openDraft(user);
    for (const item of DOSSIER_REFERENCE.cases) {
      const card = screen.getByRole('article', { name: `${item.advertiser} dossier` });
      const note = webFor(item)[0];
      expect(within(card).getByText('Web IQ — simulated')).toBeVisible();
      expect(within(card).getByText(note.headline)).toBeVisible();
      expect(within(card).getByText(/Fictional demo content, not retrieved from the web/)).toBeVisible();
      const draft = within(card).getByRole('textbox');
      expect(draft).toHaveTextContent(`Simulated web context — ${note.source}, ${note.publishedOn}`);
      expect(draft).toHaveTextContent(note.summary);
      expect(draft).toHaveTextContent(note.meetingPrompt);
      expect(within(card).queryByRole('link')).not.toBeInTheDocument();
      expect(card.lastElementChild).toHaveClass('dossier-draft');
    }
    expect(screen.getByText('Follow up on validation')).toBeVisible();
    expect(screen.getByText('No credit for this delivery gap')).toBeVisible();
    await user.click(screen.getByRole('checkbox', { name: 'Include Web IQ context' }));
    expect(screen.getAllByText('Web context is not included. No simulated web notice will be added to the draft.')).toHaveLength(2);
    for (const note of DOSSIER_WEB_CONTEXT.notes) expect(screen.queryByText(note.headline)).not.toBeInTheDocument();
    for (const item of DOSSIER_REFERENCE.cases) {
      expect(screen.getByRole('textbox', { name: `${item.advertiser} follow-up draft` })).toHaveValue(
        dossierDraft(item, qualifyDossier(item, 'action', asOf, notes, true)),
      );
    }
    expect(readLiveDossier).not.toHaveBeenCalled();
  });
  it('requires the Web IQ stage before the draft and preserves its choice across backward navigation', async () => {
    mount();
    const user = userEvent.setup();
    const navigation = screen.getByRole('navigation', { name: 'Dossier context' });
    expect(within(navigation).getAllByRole('button').map((button) => button.textContent))
      .toEqual(['1Facts', '2Contract', '3Work IQ', '4Web IQ', '5Draft']);
    fireEvent.click(screen.getByRole('button', { name: '5 Draft' }));
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '1 Facts' })).toHaveAttribute('aria-current', 'step');
    await user.click(screen.getByRole('button', { name: '4 Web IQ' }));
    await user.click(screen.getByRole('checkbox', { name: 'Include Web IQ context' }));
    await user.click(screen.getByRole('button', { name: '3 Work IQ' }));
    expect(screen.getByRole('checkbox', { name: 'Include Web IQ context' })).toBeDisabled();
    expect(screen.queryByText('Web IQ — simulated')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Review web context/ }));
    expect(screen.getByRole('checkbox', { name: 'Include Web IQ context' })).not.toBeChecked();
    await user.click(screen.getByRole('button', { name: /Prepare the draft/ }));
    expect(screen.getByRole('textbox', { name: 'Contoso Mobility follow-up draft' })).toHaveValue(
      dossierDraft(contoso, qualifyDossier(contoso, 'action', asOf, notes, true)),
    );
    await user.selectOptions(screen.getByLabelText('Evidence mode'), 'recorded');
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '5 Draft' })).toBeDisabled();
    expect(readLiveDossier).not.toHaveBeenCalled();
  });
  it('carries the Work IQ decision into Web IQ after replay without running another request', async () => {
    vi.useFakeTimers();
    vi.mocked(recordedDossiers).mockReturnValue({ capture, error: null });
    mount();
    fireEvent.click(screen.getByRole('button', { name: '3 Work IQ' }));
    expect(screen.getByRole('button', { name: '4 Web IQ' })).toBeDisabled();
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(screen.getByText('Follow up on validation')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: /Review web context/ }));
    expect(screen.getByRole('button', { name: '4 Web IQ' })).toHaveAttribute('aria-current', 'step');
    expect(screen.getByText('Follow up on validation')).toBeVisible();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByText('Replaying recorded evidence…')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Prepare the draft/ }));
    expect(screen.getAllByRole('textbox')).toHaveLength(2);
    expect(readLiveDossier).not.toHaveBeenCalled();
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
      if (path.startsWith('/preview')) expect(screen.getByRole('button', { name: 'Read live' })).toBeDisabled();
    },
  );
  it('keeps the real route behind authentication', () => {
    auth.isAuthenticated = false;
    window.history.replaceState({}, '', '/iq-in-practice');
    render(<App />);
    expect(window.location.pathname).toBe('/auth');
  });
});
