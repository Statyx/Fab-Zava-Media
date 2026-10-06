import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from '@/App';
import { dossierDraft, dossierMessage, dossierPrompt, qualifyDossier, relevantWebNotes, relevantWorkCase, webDraftContext, withWorkContext, type DossierCapture, type DossierCase } from '@/domain/dossier';
import { DOSSIER_REFERENCE, DOSSIER_WEB_CONTEXT, DOSSIER_WORK_CONTEXT, graphCampaignIds, recordedDossiers, validateCapture } from '@/services/dossier';

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
      await screen.findByRole('heading', { level: 1, name: 'What can I do for you?' }, { timeout: 5000 });
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
