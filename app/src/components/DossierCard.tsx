import { useEffect, useRef, useState } from 'react';

import { Markdown } from './Markdown';
import {
  dossierMessage, dossierPrompt, dossierStepAtLeast, qualifyDossier, relevantWorkNotes, relevantWebNotes, webDraftContext, withWorkContext, type DossierCase,
  type DossierStep, type WorkCase, type WorkNote,
} from '@/domain/dossier';
import { fmtInt, fmtPct } from '@/lib/format';
import { dossierDax, DOSSIER_REFERENCE, DOSSIER_WEB_CONTEXT } from '@/services/dossier';
import { SEND_MS } from '@/services/stage';

const SIGNAL_LABELS: Record<string, string> = {
  email: 'Outlook · email',
  teams: 'Teams · chat',
  meeting: 'Calendar · meeting',
  file: 'SharePoint · file',
};

const initials = (name: string) => name.split(' ').map((part) => part.charAt(0)).join('').slice(0, 2).toUpperCase();

interface Props {
  item: DossierCase;
  step: DossierStep;
  includeWork: boolean;
  includeFabric: boolean;
  includeFoundry: boolean;
  includeWeb: boolean;
  asOf: string;
  notes: WorkNote[];
  work?: WorkCase | null;
}

export function DossierCard({ item, step, includeWork, includeFabric, includeFoundry, includeWeb, asOf, notes, work = null }: Props) {
  const [panel, setPanel] = useState<'figures' | 'scope' | 'contract' | 'evidence' | null>(null);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const [sendState, setSendState] = useState<'idle' | 'sending' | 'sent'>('idle');
  const sendTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (sendTimer.current) clearTimeout(sendTimer.current); }, []);
  const available = includeFoundry;
  const workReady = dossierStepAtLeast(step, 'work');
  const webReady = dossierStepAtLeast(step, 'web');
  const activeWork = includeWork && workReady ? work : null;
  const action = withWorkContext(qualifyDossier(item, step, asOf, notes, includeWork, available,
    false, includeFabric), activeWork);
  const webNotes = includeWeb && webReady ? relevantWebNotes(item, DOSSIER_WEB_CONTEXT, DOSSIER_REFERENCE.scenarioId, asOf) : [];
  const facts = item.facts;
  const baseMessage = step === 'action' ? dossierMessage(item, action, activeWork, facts) : null;
  const initialMessage = baseMessage && webNotes.length
    ? `${baseMessage}\n\n${webDraftContext(webNotes)}`
    : baseMessage;
  const [message, setMessage] = useState(initialMessage ?? '');
  const workNotes = includeWork && workReady ? relevantWorkNotes(item, notes, asOf) : [];
  const recipient = activeWork?.recipient ?? null;

  function togglePanel(next: NonNullable<typeof panel>) {
    setPanel((current) => current === next ? null : next);
  }

  async function copyMessage() {
    if (!message) return;
    try {
      if (!navigator.clipboard) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(message);
      setCopyState('copied');
    } catch {
      setCopyState('failed');
    }
  }

  function sendMessage() {
    if (!recipient || !message.trim() || sendState !== 'idle') return;
    if (SEND_MS <= 0) { setSendState('sent'); return; }
    setSendState('sending');
    sendTimer.current = setTimeout(() => {
      sendTimer.current = null;
      setSendState('sent');
    }, SEND_MS);
  }

  return (
    <article className={`glass dossier-card is-${action.treatment}`} aria-label={`${item.advertiser} dossier`}>
      <header>
        <span className="dossier-avatar" aria-hidden>{item.advertiser.charAt(0)}</span>
        <div><h2>{item.advertiser}</h2><p>{item.market} · {item.quarter}</p></div>
      </header>

      <div className={`dossier-fact iq-source-fabric ${includeFabric ? '' : 'is-source-excluded'}`}>
        <span className="iq-source-badge">Fabric IQ · figures & scope</span>
        <strong>{includeFabric ? `${facts.variance > 0 ? '+' : ''}${fmtPct(facts.variance, 0)}` : '—'}</strong>
        <span>{includeFabric ? 'Delivery vs plan' : 'Figures and scope not included'}</span>
        {includeFabric ? <small>{item.campaignIds.length} campaigns · {item.market} · {item.quarter}</small> : null}
      </div>

      <div className="dossier-treatment" aria-live="polite">
        <span className="iq-eyebrow">{step === 'facts' ? 'From the figures alone' : step === 'action' ? 'Next step' : 'Treatment and next step'}</span>
        <h3>{action.title}</h3>
        <p>{action.next}</p>
      </div>

      {step !== 'facts' ? (
        <div className={`dossier-source-block iq-source-foundry ${includeFoundry ? '' : 'is-source-excluded'}`}>
          <span className="iq-source-badge">Foundry · contract context</span>
          <p>{!includeFoundry ? 'Contract context is not included. The treatment remains unqualified.'
            : item.id === 'contoso-es' ? 'Article 6.2: above 10% over-delivery, a compensation credit is required within 45 days of quarter close. Article 6.4: assess each market separately.'
                : 'Articles 6.1–6.2 exclude compensation for this delivery variance. Article 6.3 prohibits billing the excess.'}</p>
          <small>{includeFoundry ? `Foundry agents · ${item.contract.reference}` : 'Restore this context to qualify the delivery gap'}</small>
        </div>
      ) : null}

      {workReady ? (
        <div className={`dossier-source-block dossier-work-note iq-source-work ${includeWork ? '' : 'is-source-excluded'}`}>
          <span className="iq-source-badge">Work IQ</span>
          {activeWork ? (
            <>
              <ul className="dossier-signals" aria-label={`${item.advertiser} Work IQ signals`}>
                {activeWork.signals.map((signal) => (
                  <li key={signal.id} className={`is-${signal.kind}`}>
                    <span className="dossier-signal-kind">{SIGNAL_LABELS[signal.kind] ?? signal.kind} · {signal.date}</span>
                    <strong>{signal.title}</strong>
                    <small>{signal.who}</small>
                    <p>{signal.detail}</p>
                  </li>
                ))}
              </ul>
              <div className="dossier-people" aria-label="People involved">
                {activeWork.people.map((person) => (
                  <span key={person.name} className="dossier-person"><span aria-hidden>{initials(person.name)}</span>{person.name}<small>{person.role}</small></span>
                ))}
              </div>
              <div className="dossier-work-impact"><span className="iq-eyebrow">What Work IQ changes</span><p>{activeWork.impact}</p></div>
            </>
          ) : workNotes.map((note) => (
            <details key={note.id}>
              <summary>{note.authorRole} · {note.date} · Read note</summary>
              <p>“{note.text}”</p>
            </details>
          ))}
          {!includeWork ? <p>Work context is not included. What is already underway, and who owns it, is unknown.</p>
            : !activeWork && !workNotes.length ? <p>No work signal found for this case.</p> : null}
        </div>
      ) : null}

      {webReady ? (
        <div className={`dossier-source-block iq-source-web ${includeWeb ? '' : 'is-source-excluded'}`}>
          <span className="iq-source-badge">Web IQ</span>
          {webNotes.map((note) => (
            <div key={note.id} className="dossier-web-story">
              <small>{note.source} · {note.publishedOn}</small>
              <h4>{note.headline}</h4>
              <p>{note.summary}</p>
              <div className="dossier-web-relevance"><span className="iq-eyebrow">For the account meeting</span><p>{note.meetingPrompt}</p></div>
            </div>
          ))}
          {!includeWeb ? <p>Web context is not included. No public announcement will be added to the message.</p>
            : !webNotes.length ? <p>No public announcement found for this case.</p> : null}
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
              <p>Same advertiser, market and quarter.</p>
              <details className="iq-query"><summary>DAX query</summary><pre>{dossierDax(item)}</pre></details>
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
              <p>Relations: AdvertiserHasBrand, BrandHasCampaign, CampaignForAdvertiser, CampaignInMarket.</p>
              {item.id === 'contoso-es' ? <p>Article 6.4 assesses each market and quarter separately. Other markets are not netted against Spain.</p> : null}
            </>
          ) : null}
          {panel === 'contract' ? (
            <>
              <p>Verbatim excerpts from the signed agreement: {item.contract.file}.</p>
              {item.contract.articles.map((a) => <div className="dossier-article" key={a.number}><Markdown text={a.text} /></div>)}
              <p className="iq-fingerprint">Document fingerprint: {item.contract.fingerprint}</p>
            </>
          ) : null}
          {panel === 'evidence' ? (
            <>
              <p>Scenario date: {asOf}. Figures from the semantic model, scope from the ontology graph, treatment from {item.contract.reference}.</p>
              <details className="iq-query"><summary>Agent question</summary><p>{dossierPrompt(item, asOf)}</p></details>
            </>
          ) : null}
        </section>
      ) : null}
      {step === 'action' ? (
        <div className="dossier-draft dossier-send">
          <h4>Send to the right person</h4>
          {initialMessage ? (
            <>
              {recipient ? (
                <div className="dossier-recipient iq-source-work">
                  <span className="dossier-recipient-avatar" aria-hidden>{initials(recipient.name)}</span>
                  <div>
                    <strong>{recipient.name}</strong><small>{recipient.role}</small>
                    <span className="iq-source-badge">Found by Work IQ</span>
                  </div>
                  <ul aria-label={`Why ${recipient.name}`}>{recipient.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
                </div>
              ) : (
                <p className="dossier-recipient is-unknown">Recipient unknown. Include Work IQ to find who owns the next step.</p>
              )}
              <div className="dossier-draft-sources" aria-label="Context included in this message">
                <span className="iq-source-badge iq-source-fabric">Fabric IQ · facts</span>
                <span className="iq-source-badge iq-source-foundry">Foundry · clauses</span>
                {activeWork ? <span className="iq-source-badge iq-source-work">Work IQ · recipient & context</span>
                  : action.notes.length ? <span className="iq-source-badge iq-source-work">Work IQ · note</span> : null}
                {webNotes.length ? <span className="iq-source-badge iq-source-web">Web IQ · announcement</span> : null}
              </div>
              <textarea value={message} onChange={(e) => setMessage(e.target.value)} readOnly={sendState !== 'idle'}
                aria-label={`${item.advertiser} message`} rows={webNotes.length ? 10 : 6} />
              <div className="dossier-send-actions">
                <button className="iq-button is-primary" disabled={!recipient || !message.trim() || sendState !== 'idle'} onClick={sendMessage}>
                  {sendState === 'sending' ? <><span className="iq-spinner" aria-hidden />Sending…</>
                    : sendState === 'sent' ? 'Sent' : `Send in ${recipient?.channel ?? 'Teams'}`}
                </button>
                <button className="iq-button" onClick={() => void copyMessage()}>Copy message</button>
              </div>
              {sendState === 'sent' && recipient ? <p role="status" className="dossier-sent">              Sent to {recipient.name} in {recipient.channel}.</p> : null}
                            {copyState === 'copied' ? <span role="status">Copied.</span> : null}
              {copyState === 'failed' ? <p role="alert">Clipboard access failed. Select and copy the message above manually.</p> : null}
            </>
          ) : <p className="iq-footnote">A definitive message is withheld until the required figures, scope and contract evidence are included and consistent.</p>}
        </div>
      ) : null}
    </article>
  );
}
