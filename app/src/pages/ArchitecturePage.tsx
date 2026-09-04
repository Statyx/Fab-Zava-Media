import { ChainDiagram } from '@/components/ChainDiagram';
import { Section } from '@/components/Section';
import { CHAIN_NODES, PLANE_LABEL, type Plane } from '@/domain/chain';

/**
 * How the thing is wired, and the one rule that governs it.
 *
 * Second-rank in the nav on purpose: nobody opens a media console to read an architecture. It
 * exists for the technical question that lands in the ten minutes after a demo — "what is this
 * actually made of" — and it answers that with a picture, because a numbered list of seven
 * layers is a picture badly drawn.
 *
 * It used to carry a third section listing what the deployment cost us: permission propagation
 * answering 404, a paused capacity answering 404 too, tool approval being per agent. Accurate,
 * hard-won, and none of the customer's business — an app is not the place to prove our own
 * homework. That material belongs in the runbook, not on screen.
 *
 * It is listed in `SECONDARY_NAV`, not `NAV`. For a while it was in neither, which meant the
 * route was reachable only by typing the URL and the page rendered with no heading at all.
 */
const PLANES: Plane[] = ['foundry', 'fabric', 'semantic', 'ontology'];

export function ArchitecturePage() {
  return (
    <>
      <Section
        id="chain"
        title="The deployed chain"
        provenance="Sweden Central — a single region, one copy of the data"
      >
        <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs">
          {PLANES.map((p) => (
            <span key={p} className={`wf-key is-${p}`}>
              {PLANE_LABEL[p]}
            </span>
          ))}
        </div>

        <div className="mt-4">
          <ChainDiagram />
        </div>

        {/* The box holds a label the width allows; the sentence that explains the component
            belongs here, where the browser wraps it properly. */}
        <dl className="mt-4 grid gap-x-6 gap-y-2 sm:grid-cols-2">
          {CHAIN_NODES.map((n) => (
            <div key={n.id} className="grid grid-cols-[auto_1fr] items-baseline gap-2">
              <dt className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>
                {n.label}
              </dt>
              <dd className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                {n.role}
              </dd>
            </div>
          ))}
        </dl>
      </Section>

      <Section id="boundary" title="The boundary rule">
        <p className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          The data agent computes and does not conclude. The contract agent cites and does not
          compute. The supervisor does neither: it asks both questions and reconciles the
          answers. No single layer can produce an answer to a cross-source question on its own,
          and that is the property that makes the chain auditable.
        </p>
        <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          Practical consequence: performance data carries no contractual term. An entitlement
          question is always answered from the signed agreement, for the account it belongs to.
        </p>
      </Section>
    </>
  );
}
