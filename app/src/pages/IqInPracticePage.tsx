import { useEffect, useRef, useState } from 'react';

import { DossierCard } from '@/components/DossierCard';
import { IqContributionControls, type IqContributions } from '@/components/IqContributionControls';
import { useQuerySource } from '@/data/querySource';
import { DOSSIER_STEPS, dossierStepAtLeast, type DossierCapture, type DossierStep, type EvidenceMode } from '@/domain/dossier';
import { IQ_NAV } from '@/domain/nav';
import { DOSSIER_REFERENCE, readLiveDossier, recordedDossiers } from '@/services/dossier';
import { REPLAY_MS } from '@/services/frozen';
import './IqInPracticePage.css';

export function IqInPracticePage() {
  const { preview } = useQuerySource();
  const recorded = recordedDossiers();
  const [step, setStep] = useState<DossierStep>('facts');
  const [mode, setMode] = useState<EvidenceMode>(() => recorded.capture ? 'recorded' : 'repository');
  const [includeWork, setIncludeWork] = useState(true);
  const [includeFabric, setIncludeFabric] = useState(true);
  const [includeFoundry, setIncludeFoundry] = useState(true);
  const [includeWeb, setIncludeWeb] = useState(true);
  const [webReviewed, setWebReviewed] = useState(false);
  const [evidence, setEvidence] = useState<DossierCapture['cases']>([]);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const generation = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function clearPending() {
    generation.current += 1;
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  }
  useEffect(() => () => {
    generation.current += 1;
    if (timer.current) clearTimeout(timer.current);
  }, []);

  function reset(nextMode = mode) {
    clearPending();
    setStep('facts');
    setMode(nextMode);
    setIncludeWork(true);
    setIncludeFabric(true);
    setIncludeFoundry(true);
    setIncludeWeb(true);
    setWebReviewed(false);
    setEvidence([]);
    setBusy(false);
    setError(null);
    setProgress('');
    setRevision((v) => v + 1);
  }

  function reveal(target: DossierStep) {
    setStep(target);
    if (target === 'web') setWebReviewed(true);
    setRevision((v) => v + 1);
  }

  function changeContribution(key: keyof IqContributions, checked: boolean) {
    if (key === 'fabric') setIncludeFabric(checked);
    if (key === 'foundry') setIncludeFoundry(checked);
    if (key === 'work') setIncludeWork(checked);
    if (key === 'web') setIncludeWeb(checked);
    setRevision((v) => v + 1);
  }

  async function advance(target: DossierStep, selectedMode = mode, refresh = false) {
    if (busy || (target === 'action' && !webReviewed)) return;
    if (target === 'facts') { reset(selectedMode); return; }
    setError(null);
    if (selectedMode === 'repository' || (!refresh && selectedMode === mode && evidence.length === DOSSIER_REFERENCE.cases.length)) {
      reveal(target);
      return;
    }
    if (selectedMode === 'recorded' && !recorded.capture) {
      setError(recorded.error);
      return;
    }
    if (selectedMode === 'live' && preview) {
      setError('Live reads are disabled in the design preview. Open the signed-in app.');
      return;
    }
    clearPending();
    const current = generation.current;
    setMode(selectedMode);
    setStep('facts');
    setWebReviewed(false);
    setEvidence([]);
    setRevision((v) => v + 1);
    setBusy(true);
    if (selectedMode === 'recorded' && recorded.capture) {
      const capturedCases = recorded.capture.cases;
      setProgress('Replaying recorded evidence…');
      timer.current = setTimeout(() => {
        if (generation.current !== current) return;
        timer.current = null;
        setEvidence(capturedCases);
        setBusy(false);
        reveal(target);
      }, REPLAY_MS);
      return;
    }
    try {
      const results: DossierCapture['cases'] = [];
      for (const item of DOSSIER_REFERENCE.cases) {
        const result = await readLiveDossier(item, (message) => {
          if (generation.current === current) setProgress(`${item.advertiser}: ${message}`);
        });
        if (generation.current !== current) return;
        results.push(result);
      }
      setEvidence(results);
      reveal(target);
    } catch (err) {
      if (generation.current === current) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (generation.current === current) setBusy(false);
    }
  }

  const unavailable = mode === 'recorded' && !recorded.capture;
  const next = DOSSIER_STEPS[DOSSIER_STEPS.findIndex((s) => s.id === step) + 1]?.id;
  const nextLabel = step === 'facts' ? 'Review the context' : step === 'contract' ? 'Add work context'
    : step === 'work' ? 'Review web context' : 'Prepare the draft';
  const sourceLabel = mode === 'repository' ? 'Repository example · not live'
    : mode === 'recorded' ? 'Recorded evidence' : evidence.length ? 'Live evidence · demo data' : 'Live mode · not yet read';

  return (
    <div className="iq-page dossier-page">
      <header className="iq-intro">
        <div>
          <span className="cover-eyebrow glass">{IQ_NAV.label}</span>
          <h1>Which delivery gaps need action?</h1>
          <p>Start with the figures. Check the agreement. Then see what is already underway.</p>
        </div>
        <span className="iq-badge">{sourceLabel}</span>
      </header>

      <div className="glass dossier-toolbar">
        <div><strong>Q3 close scenario</strong><span>{new Date(`${DOSSIER_REFERENCE.asOf}T00:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })} · fictional accounts and contracts</span></div>
        <label>Evidence
          <select aria-label="Evidence mode" value={mode} onChange={(e) => {
            const selected = e.target.value;
            if (selected === 'repository' || selected === 'recorded' || selected === 'live') reset(selected);
          }}>
            <option value="recorded">Recorded evidence</option>
            <option value="repository">Repository example</option>
            <option value="live" disabled={preview}>Live on request</option>
          </select>
        </label>
        <button className="iq-button" onClick={() => reset()}>Reset</button>
      </div>

      {unavailable ? (
        <div className="dossier-availability" role="note">
          <p><strong>Recorded evidence is not available yet.</strong> {recorded.error}</p>
          <p>The figures below are repository data. Choose the local example to explore the storyboard without presenting it as a Fabric or Foundry recording.</p>
          <button className="iq-button" onClick={() => reset('repository')}>Explore repository example</button>
        </div>
      ) : null}

      <nav className="dossier-steps" aria-label="Dossier context">
        {DOSSIER_STEPS.map((s, index) => (
          <button key={s.id} aria-current={step === s.id ? 'step' : undefined}
            disabled={busy || (unavailable && s.id !== 'facts') || (s.id === 'action' && !webReviewed)}
            title={s.id === 'action' && !webReviewed ? 'Review the Web IQ step before preparing the draft.' : undefined}
            onClick={() => void advance(s.id)}>
            <span>{index + 1}</span>{s.label}
          </button>
        ))}
      </nav>

      <div className="dossier-stage-copy" aria-live="polite">
        {!includeFabric ? <><strong>The measured gap is not included.</strong><span>Other context cannot establish the figures or the campaign scope.</span></>
          : step !== 'facts' && !includeFoundry ? <><strong>The contractual treatment is not established.</strong><span>Figures and work notes do not replace the applicable agreement.</span></>
          : step === 'facts' ? <><strong>Two similar gaps. Treatment still unknown.</strong><span>The figures identify the variance, not the contractual response.</span></>
          : step === 'contract' ? <><strong>Similar figures. Different obligations.</strong><span>The agreement changes the treatment, not the measurement.</span></>
          : step === 'work' ? <><strong>Before asking someone to start, check what is underway.</strong><span>Work IQ is simulated here. Reported progress is not proof of approval or issuance.</span></>
          : step === 'web' ? <><strong>An upcoming campaign adds context to the meeting.</strong><span>These Web IQ notices are fictional. Include them in the draft or leave them out; they do not change the contract treatment.</span></>
          : <><strong>The next step, with its context.</strong><span>Review before use. Nothing is sent, approved or issued by this page.</span></>}
      </div>

      <IqContributionControls
        value={{ fabric: includeFabric, foundry: includeFoundry, work: includeWork, web: includeWeb }}
        onChange={changeContribution} busy={busy}
        contractReady={dossierStepAtLeast(step, 'contract')}
        workReady={dossierStepAtLeast(step, 'work')} webReady={dossierStepAtLeast(step, 'web')}
      />

      <div className="dossier-cards">
        {DOSSIER_REFERENCE.cases.map((item) => {
          const recordedCase = mode === 'recorded' ? recorded.capture?.cases.find((c) => c.id === item.id) : undefined;
          return (
          <DossierCard
            key={`${item.id}:${revision}`} item={item} step={step} mode={mode}
            includeFabric={includeFabric} includeFoundry={includeFoundry} includeWeb={includeWeb}
            includeWork={includeWork} evidence={evidence.find((c) => c.id === item.id)}
            factEvidence={recordedCase ? { facts: recordedCase.facts, capturedAt: recordedCase.capturedAt } : undefined}
            asOf={DOSSIER_REFERENCE.asOf} notes={DOSSIER_REFERENCE.workNotes}
          />
          );
        })}
      </div>

      {busy ? <p role="status" className="dossier-progress">{progress}</p> : null}
      {error ? (
        <div role="alert" className="iq-error">
          <strong>The requested evidence could not be loaded</strong><p>{error}</p>
          <div className="dossier-error-actions">
            <button className="iq-button" disabled={busy} onClick={() => void advance('contract', mode, true)}>Retry</button>
            {mode === 'live' && recorded.capture ? <button className="iq-button" onClick={() => reset('recorded')}>Use recorded evidence</button> : null}
            <button className="iq-button" onClick={() => reset('repository')}>Choose repository example</button>
          </div>
        </div>
      ) : null}
      {next ? (
        <div className="dossier-next"><button className="iq-button is-primary" disabled={busy || unavailable} onClick={() => void advance(next)}>
          {busy ? 'Loading evidence…' : nextLabel}<span aria-hidden> →</span>
        </button></div>
      ) : null}

      <footer className="glass dossier-explanation">
        <details>
          <summary>How IQ contributes</summary>
          <div className="dossier-contributions">
            <div><strong>Business data</strong><p>Existing demo files represent the Databricks outputs. No Databricks connection is exercised here.</p></div>
            <div className="iq-source-fabric"><strong>Fabric IQ</strong><p>The semantic model provides measures. The ontology and its graph expose the related campaigns, brands and markets.</p></div>
            <div className="iq-source-foundry"><strong>Foundry agents</strong><p>The existing agents retrieve and cite the agreements. This is not a claim that a Foundry IQ knowledge base has been deployed.</p></div>
            <div className="iq-source-work"><strong>Work IQ <span className="iq-badge">simulated</span></strong><p>A fictional Finance note adds reported work progress. No Microsoft 365 data, permissions or retrieval are being tested.</p></div>
            <div className="iq-source-web"><strong>Web IQ <span className="iq-badge">simulated</span></strong><p>Fictional Contoso and Litware announcements illustrate public context for the meeting. They stay labelled as simulated in the draft, without changing contractual conclusions. No web retrieval is performed.</p><a href="https://www.microsoft.com/en-us/WebIQ" target="_blank" rel="noreferrer">Web IQ overview · limited access</a></div>
          </div>
          <p className="iq-footnote">The extra context helps qualify the next step. It does not prove faster queries or an exclusive capability versus Databricks. The account lead retains the decision.</p>
        </details>
        <div className="dossier-footer-actions">
          <span>All actions on this page are read-only.</span>
          <button className="iq-button" disabled={preview || busy} onClick={() => void advance('contract', 'live', true)}>Read live</button>
        </div>
        {preview ? <p className="iq-footnote">Live reads are disabled in the development preview.</p> : null}
      </footer>
    </div>
  );
}
