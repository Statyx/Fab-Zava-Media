import { useState } from 'react';

import { Markdown } from './Markdown';
import {
  checkContractEvidence, dossierDraft, dossierPrompt, dossierStepAtLeast, qualifyDossier, relevantWorkNotes, relevantWebNotes, webDraftContext, type DossierCase, type DossierCapture,
  type DossierStep, type EvidenceMode, type WorkNote,
} from '@/domain/dossier';
import { fmtInt, fmtPct } from '@/lib/format';
import { dossierDax, DOSSIER_REFERENCE, DOSSIER_WEB_CONTEXT } from '@/services/dossier';

interface Props {
  item: DossierCase;
  step: DossierStep;
  mode: EvidenceMode;
  includeWork: boolean;
  includeFabric: boolean;
  includeFoundry: boolean;
  includeWeb: boolean;
  evidence?: DossierCapture['cases'][number];
  factEvidence?: Pick<DossierCapture['cases'][number], 'facts' | 'capturedAt'>;
  asOf: string;
  notes: WorkNote[];
}

export function DossierCard({ item, step, mode, includeWork, includeFabric, includeFoundry, includeWeb, evidence, factEvidence, asOf, notes }: Props) {
  const [panel, setPanel] = useState<'figures' | 'scope' | 'contract' | 'evidence' | null>(null);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const grounding = evidence ? checkContractEvidence(item, evidence) : null;
  const available = includeFoundry && (mode === 'repository' || grounding?.status === 'confirmed');
  const action = qualifyDossier(item, step, asOf, notes, includeWork, available,
    includeFoundry && grounding?.status === 'contradictory', includeFabric);
  const workReady = dossierStepAtLeast(step, 'work');
  const webReady = dossierStepAtLeast(step, 'web');
  const webNotes = includeWeb && webReady ? relevantWebNotes(item, DOSSIER_WEB_CONTEXT, DOSSIER_REFERENCE.scenarioId, asOf) : [];
  const baseDraft = step === 'action' ? dossierDraft(item, action) : null;
  const draft = baseDraft && webNotes.length
    ? `${baseDraft}\n\n${webDraftContext(webNotes)}`
    : baseDraft;
  const workNotes = includeWork && workReady ? relevantWorkNotes(item, notes, asOf) : [];
  const factSource = evidence ?? factEvidence;
  const origin = factSource
    ? `${mode === 'live' ? 'Live' : 'Recorded'} · ${new Date(factSource.capturedAt).toLocaleDateString('en-GB')}`
    : 'Repository reference';
  const facts = factSource?.facts ?? item.facts;

  function togglePanel(next: NonNullable<typeof panel>) {
    setPanel((current) => current === next ? null : next);
  }

  async function copyDraft() {
    if (!draft) return;
    try {
      if (!navigator.clipboard) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(draft);
      setCopyState('copied');
    } catch {
      setCopyState('failed');
    }
  }

  return (
    <article className={`glass dossier-card is-${action.treatment}`} aria-label={`${item.advertiser} dossier`}>
      <header>
        <span className="dossier-avatar" aria-hidden>{item.advertiser.charAt(0)}</span>
        <div><h2>{item.advertiser}</h2><p>{item.market} · {item.quarter}</p></div>
        <span className="dossier-origin">{origin}</span>
      </header>

      <div className={`dossier-fact iq-source-fabric ${includeFabric ? '' : 'is-source-excluded'}`}>
        <span className="iq-source-badge">Fabric IQ · figures & scope</span>
        <strong>{includeFabric ? `${facts.variance > 0 ? '+' : ''}${fmtPct(facts.variance, 0)}` : '—'}</strong>
        <span>{includeFabric ? 'Delivery vs plan' : 'Figures and scope not included'}</span>
        {includeFabric ? <small>{item.campaignIds.length} campaigns · {item.market} · {item.quarter}</small> : null}
      </div>

      {step !== 'facts' && includeFoundry && grounding && grounding.status !== 'confirmed'
        ? <p role="alert" className="iq-error">{grounding.reason}</p> : null}

      <div className="dossier-treatment" aria-live="polite">
        <span className="iq-eyebrow">{step === 'facts' ? 'From the figures alone' : step === 'action' ? 'Next step' : 'Treatment and next step'}</span>
        <h3>{action.title}</h3>
        <p>{action.next}</p>
      </div>

      {step !== 'facts' ? (
        <div className={`dossier-source-block iq-source-foundry ${includeFoundry ? '' : 'is-source-excluded'}`}>
          <span className="iq-source-badge">Foundry · contract context</span>
          <p>{!includeFoundry ? 'Contract context is not included. The treatment remains unqualified.'
            : !available ? 'The agreement has not been established by the available evidence.'
              : item.id === 'contoso-es' ? 'Article 6.2: above 10% over-delivery, a compensation credit is required within 45 days of quarter close. Article 6.4: assess each market separately.'
                : 'Articles 6.1–6.2 exclude compensation for this delivery variance. Article 6.3 prohibits billing the excess.'}</p>
          <small>{includeFoundry ? 'Existing Foundry agents · fictional agreement' : 'Restore this context to qualify the delivery gap'}</small>
        </div>
      ) : null}

      {workReady ? (
        <div className={`dossier-source-block dossier-work-note iq-source-work ${includeWork ? '' : 'is-source-excluded'}`}>
          <span className="iq-source-badge">Work IQ — simulated</span>
          {workNotes.map((note) => (
            <details key={note.id}>
              <summary>{note.authorRole} · {note.date} · Read simulated note</summary>
              <p>“{note.text}”</p>
              <small>Fictional scenario note · {note.id}</small>
            </details>
          ))}
          {!includeWork ? <p>Work context is not included. What is already underway is unknown.</p>
            : !workNotes.length ? <p>No applicable work note in this simulation. Actual work status is not established.</p> : null}
          <small>{item.id === 'contoso-es' ? 'Contribution: avoid requesting preparation a second time.' : 'Contribution: surface any work already underway; no matching note is supplied for this case.'}</small>
        </div>
      ) : null}

      {webReady ? (
        <div className={`dossier-source-block iq-source-web ${includeWeb ? '' : 'is-source-excluded'}`}>
          <span className="iq-source-badge">Web IQ — simulated</span>
          {webNotes.map((note) => (
            <div key={note.id} className="dossier-web-story">
              <small>{note.source} · {note.publishedOn}</small>
              <h4>{note.headline}</h4>
              <p>{note.summary}</p>
              <div className="dossier-web-relevance"><span className="iq-eyebrow">For the account meeting</span><p>{note.meetingPrompt}</p></div>
              <details className="iq-query"><summary>Fictional source details</summary><p>{note.id} · scenario date {asOf}. This notice was written for the demo; no real article or web search is being cited.</p></details>
            </div>
          ))}
          {!includeWeb ? <p>Web context is not included. No simulated web notice will be added to the draft.</p>
            : !webNotes.length ? <p>No applicable simulated web notice for this case and scenario date.</p> : null}
          <small>Fictional demo content, not retrieved from the web. It does not change the Q3 figures or the contract treatment.</small>
        </div>
      ) : null}

      {step !== 'facts' ? (
        <div className="dossier-unknowns">
          <span className="iq-eyebrow">Still to confirm</span>
          <ul>{action.unknowns.map((unknown) => <li key={unknown}>{unknown}</li>)}</ul>
        </div>
      ) : null}

      <div className="dossier-proof-buttons" role="group" aria-label={`${item.advertiser} sources`}>
        <button className="iq-source-fabric" disabled={!includeFabric} aria-expanded={panel === 'figures'} onClick={() => togglePanel('figures')}>Figures</button>
        <button className="iq-source-fabric" disabled={!includeFabric} aria-expanded={panel === 'scope'} onClick={() => togglePanel('scope')}>Why this scope?</button>
        {step !== 'facts' && available ? <button className="iq-source-foundry" aria-expanded={panel === 'contract'} onClick={() => togglePanel('contract')}>Contract articles</button> : null}
        <button aria-expanded={panel === 'evidence'} onClick={() => togglePanel('evidence')}>All evidence</button>
      </div>

      {panel ? (
        <section className={`dossier-proof ${panel === 'contract' ? 'iq-source-foundry' : panel === 'figures' || panel === 'scope' ? 'iq-source-fabric' : ''}`} aria-label={`${item.advertiser} ${panel} evidence`}>
          <div className="dossier-proof-heading"><strong>{panel === 'scope' ? 'Why this scope?' : panel === 'contract' ? item.contract.reference : 'Evidence'}</strong>
            <button aria-label="Close evidence" onClick={() => setPanel(null)}>×</button>
          </div>
          {panel === 'figures' ? (
            <>
              <dl><dt>Planned impressions</dt><dd>{fmtInt(facts.planned)}</dd><dt>Delivered impressions</dt><dd>{fmtInt(facts.delivered)}</dd><dt>Delivery vs Plan %</dt><dd>{fmtPct(facts.variance, 2)}</dd></dl>
              <p>{origin}. Same advertiser, market and quarter. Source files represent Databricks outputs; no Databricks call is made.</p>
              <details className="iq-query"><summary>{evidence ? 'Executed DAX' : 'DAX template — not executed here'}</summary><pre>{evidence?.dax ?? dossierDax(item)}</pre></details>
            </>
          ) : null}

          {panel === 'scope' ? (
            <>
              <div className="dossier-scope-chain">
                <strong>{item.advertiser}</strong><span aria-hidden>↓</span>
                <span>{[...new Set(item.campaigns.map((c) => c.brand))].join(' · ')}</span><span aria-hidden>↓</span>
                <strong>{item.campaignIds.length} campaigns</strong><span aria-hidden>↓</span>
                <span>{item.market} · {item.quarter}</span>
              </div>
              <ul>{item.campaigns.map((c) => <li key={c.id}>{c.name}<small>{c.id}</small></li>)}</ul>
              <p>Relations: AdvertiserHasBrand, BrandHasCampaign, CampaignForAdvertiser, CampaignInMarket. {evidence ? 'The recorded graph query confirms campaign membership; brand labels come from the repository reference.' : 'This scope comes from the repository tables and ontology bindings, not a live graph query.'}</p>
              {item.id === 'contoso-es' ? <p>Article 6.4 assesses each market and quarter separately. Other markets are not netted against Spain.</p> : null}
              {evidence ? <details className="iq-query"><summary>Executed graph query</summary><pre>{evidence.gql}</pre></details> : null}
            </>
          ) : null}
          {panel === 'contract' ? (
            <>
              <p>Verbatim excerpts from the fictional repository agreement: {item.contract.file}. These excerpts are not generated agent prose.</p>
              {item.contract.articles.map((a) => <div className="dossier-article" key={a.number}><Markdown text={a.text} /></div>)}
              <p className="iq-fingerprint">Document fingerprint: {item.contract.fingerprint}</p>
            </>
          ) : null}
          {panel === 'evidence' ? (
            <>
              <p>Scenario date: {asOf}. {origin}. Work IQ and Web IQ are simulated, not connected.</p>
              <p>The deterministic case treatment is checked against the two fictional agreements. The agent evidence below is kept separate; it is not an approval or proof of issuance.</p>
              {evidence ? (
                <>
                  <span className="iq-badge">{origin} · source-read duration {evidence.seconds.toFixed(1)} s</span>
                  <Markdown text={evidence.text} />
                  <p>Reported tools: {evidence.toolsFired.join(', ')}. Invocation alone is not proof of a correct interpretation.</p>
                  {evidence.citations.map((c, i) => <p key={i}>{c.label}{c.detail ? ` — ${c.detail}` : ''}</p>)}
                </>
              ) : <p>{factEvidence ? 'The recorded answer is revealed only after completing the disclosed replay.' : 'No executed Fabric/Foundry answer is being shown in this reference view.'}</p>}
              <details className="iq-query"><summary>Exact agent question</summary><p>{dossierPrompt(item, asOf)}</p></details>
            </>
          ) : null}
        </section>
      ) : null}
      {step === 'action' ? (
        <div className="dossier-draft">
          <h4>Draft — review before use</h4>
          {draft ? (
            <>
              <div className="dossier-draft-sources" aria-label="Context included in this draft">
                <span className="iq-source-badge iq-source-fabric">Fabric IQ · facts</span>
                <span className="iq-source-badge iq-source-foundry">Foundry · clauses</span>
                {action.notes.length ? <span className="iq-source-badge iq-source-work">Work IQ · simulated note</span> : null}
                {webNotes.length ? <span className="iq-source-badge iq-source-web">Web IQ · simulated notice</span> : null}
              </div>
              <textarea readOnly value={draft} aria-label={`${item.advertiser} follow-up draft`} rows={webNotes.length ? 9 : 5} />
              <button className="iq-button" onClick={() => void copyDraft()}>Copy draft</button>
              {copyState === 'copied' ? <span role="status">Copied. Nothing has been sent.</span> : null}
              {copyState === 'failed' ? <p role="alert">Clipboard access failed. Select and copy the draft above manually.</p> : null}
            </>
          ) : <p className="iq-footnote">A definitive draft is withheld until the required figures, scope and contract evidence are included and consistent.</p>}
        </div>
      ) : null}
    </article>
  );
}
