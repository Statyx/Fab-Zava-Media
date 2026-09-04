import { Section } from '@/components/Section';
import { AGREEMENTS, REGIME_STYLE } from '@/data/contracts';
import { useAssistant } from '@/domain/assistant';

/**
 * The contracts, and deliberately not a single figure.
 *
 * This is the one section that produces no measure, and that emptiness is the argument: the
 * entitlement is not in the warehouse. Adding a KPI strip here to make the page look balanced
 * would undo the whole demonstration.
 *
 * The summaries below are captions, not answers. Clicking one asks the corpus, and what comes
 * back carries its own citation. The app must never let a caption pass for evidence.
 */
export function ContractsPage() {
  const { askText } = useAssistant();

  return (
    <>
      <Section
        id="regimes"
        title="Five master agreements, three regimes"
        provenance="Signed master agreements ADV-001 to ADV-005"
      >
        <p className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          Three variances of the same size can produce three opposite outcomes, depending on the
          regime the campaign sits under: compensation, a make-good in kind, or nothing owed at
          all. The agreement is what decides.
        </p>

        <div className="mt-4 space-y-2">
          {AGREEMENTS.map((a) => {
            const style = REGIME_STYLE[a.regime];
            return (
              <button
                key={a.id}
                onClick={() =>
                  askText(
                    `In the ${a.advertiser} master agreement, what exactly does the delivery ` +
                      `clause provide for? Cite the article and say, in one sentence, what the ` +
                      `agency must do if the variance exceeds the tolerance. Use no delivery ` +
                      `figures: this question is about the text alone.`,
                  )
                }
                className="block w-full rounded-lg p-3 text-left transition hover:bg-[var(--bg-secondary)] focus-visible:outline-2 focus-visible:outline-offset-2"
                style={{ borderLeft: `3px solid ${style.tone}` }}
              >
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
                    {a.advertiser}
                  </span>
                  <span
                    className="rounded px-1.5 py-0.5 text-[0.625rem] font-semibold"
                    style={{ color: style.tone }}
                  >
                    {style.label}
                  </span>
                  <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                    {a.id} · {a.article}
                  </span>
                </div>
                <p className="mt-1 text-sm leading-snug" style={{ color: 'var(--text-secondary)' }}>
                  {a.summary}
                </p>
              </button>
            );
          })}
        </div>
      </Section>

      <Section id="boundary" title="Where an entitlement is decided">
        <p className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          A delivery variance is a fact. Whether it entitles the advertiser to compensation, to
          a make-good, or to an audit is decided by the master agreement — and the terms differ
          by account. That is why the figure alone never settles a claim.
        </p>
        <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          It also has to hold up under scrutiny: the Sapin law requires the agency to be able to{' '}
          <em>show</em> how a billed figure was produced. Two competing definitions of "delivered
          impressions" is not a reporting inconvenience — it is an audit exposure.
        </p>
      </Section>
    </>
  );
}
