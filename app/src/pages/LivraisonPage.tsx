import { QueryState } from '@/components/QueryState';
import { Section } from '@/components/Section';
import { AGREEMENTS, REGIME_STYLE, agreementFor } from '@/data/contracts';
import { CHANNEL_DAX, VARIANCE_DAX, mapChannels, mapVariance } from '@/data/queries';
import type { MarketVariance } from '@/data/queries';
import { useAssistant } from '@/domain/assistant';
import { OPENERS } from '@/domain/openers';
import { fmtDec, fmtEur, fmtInt, fmtPct } from '@/lib/format';
import { useDax } from '@/hooks/useDax';

/**
 * The tolerance band the contracts are written around.
 *
 * Rendered as a line on the chart rather than used to filter the query: the point of the panel
 * is that the reader sees where the band is and judges the overshoot themselves. A table
 * pre-filtered to "the bad ones" asks the room to trust the filter.
 */
const TOLERANCE = 5;

/** The widest bar in the chart, so every row is drawn on the same scale. */
function scale(rows: MarketVariance[]): number {
  return Math.max(TOLERANCE * 2, ...rows.map((r) => Math.abs(r.variance)));
}

/**
 * Planned against delivered, and what the contract makes of it.
 *
 * The chart is the way into the question: every row is a button, and clicking it asks a
 * `mixed` question about that market rather than opening a drill-down. A row that only sorts
 * is a row that teaches the room nothing.
 *
 * The three cases that matter are never named in this file. They have to emerge from the same
 * ranking as everything else — naming them here would turn a finding into a lookup.
 */
export function LivraisonPage() {
  const { ask, askText } = useAssistant();
  const variance = useDax(VARIANCE_DAX, mapVariance);
  const channels = useDax(CHANNEL_DAX, mapChannels);

  const rows = variance.data ?? [];
  const max = scale(rows);
  const breaches = rows.filter((r) => Math.abs(r.variance) > TOLERANCE);

  return (
    <>
      <Section
        id="ecarts"
        title="Écart entre le plan et la diffusion"
        provenance="Modèle sémantique — Delivery vs Plan %, signé : positif = sur-livraison"
        action={
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            tolérance ±{TOLERANCE} %
          </span>
        }
      >
        <QueryState
          loading={variance.loading}
          error={variance.error}
          empty={!variance.loading && rows.length === 0}
          onRetry={variance.reload}
        >
          <p className="mb-3 text-sm" style={{ color: 'var(--text-secondary)' }}>
            {breaches.length} couple(s) hors tolérance. Cliquez une ligne pour demander ce que
            le contrat prévoit en face.
          </p>

          <div className="space-y-1">
            {rows.slice(0, 12).map((r) => {
              const over = r.variance >= 0;
              const width = (Math.abs(r.variance) / max) * 50;
              const breach = Math.abs(r.variance) > TOLERANCE;
              const agreement = agreementFor(r.advertiser);
              return (
                <button
                  key={`${r.advertiser}-${r.market}-${r.quarter}`}
                  onClick={() =>
                    askText(
                      `Pour ${r.advertiser} sur le marché ${r.market} au trimestre ${r.quarter}, ` +
                        `l'écart mesuré est de ${fmtPct(r.variance, 2)} entre ` +
                        `[Planned Impressions] et [Delivered Impressions]. Que prévoit le contrat ` +
                        `cadre de cet annonceur en pareil cas, et le client a-t-il droit à quelque ` +
                        `chose ? Cite l'article.`,
                    )
                  }
                  className="grid w-full grid-cols-[1fr_auto] items-center gap-3 rounded-lg px-3 py-2 text-left transition hover:bg-[var(--bg-secondary)] focus-visible:outline-2 focus-visible:outline-offset-2"
                >
                  <div className="min-w-0">
                    <div className="flex items-baseline gap-2">
                      <span
                        className="truncate text-sm font-medium"
                        style={{ color: 'var(--text-primary)' }}
                      >
                        {r.advertiser} · {r.market}
                      </span>
                      <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                        {r.quarter}
                      </span>
                      {breach && agreement ? (
                        <span
                          className="rounded px-1.5 py-0.5 text-[0.625rem] font-semibold"
                          style={{ color: REGIME_STYLE[agreement.regime].tone }}
                        >
                          {REGIME_STYLE[agreement.regime].label}
                        </span>
                      ) : null}
                    </div>

                    {/* A diverging bar centred on plan: the sign is what selects the
                        contractual regime, so it must be visible before the number is read. */}
                    <div
                      className="relative mt-1.5 h-2 rounded"
                      style={{ background: 'var(--bg-secondary)' }}
                    >
                      <span
                        className="absolute inset-y-0 w-px"
                        style={{ left: '50%', background: 'var(--border-strong)' }}
                      />
                      <span
                        className="absolute inset-y-0 block rounded"
                        style={{
                          left: over ? '50%' : `${50 - width}%`,
                          width: `${width}%`,
                          background: breach
                            ? over
                              ? 'var(--sev-critical)'
                              : 'var(--sev-high)'
                            : 'var(--sev-low)',
                        }}
                      />
                    </div>

                    <span className="mt-1 block text-xs" style={{ color: 'var(--text-muted)' }}>
                      {fmtInt(r.planned)} planifiées · {fmtInt(r.delivered)} diffusées
                    </span>
                  </div>

                  <span
                    className="text-sm font-semibold tabular-nums"
                    style={{ color: breach ? 'var(--sev-critical)' : 'var(--text-secondary)' }}
                    title="Mesure Delivery vs Plan % — modèle sémantique"
                  >
                    {r.variance >= 0 ? '+' : ''}
                    {fmtPct(r.variance, 2)}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Three regimes, side by side, so the reader sees that the figure does not decide
              the outcome. This is the demo in one glance. */}
          <div className="mt-4 grid gap-2 @3xl:grid-cols-3">
            {(['due', 'excluded', 'penalty'] as const).map((regime) => {
              const style = REGIME_STYLE[regime];
              const who = AGREEMENTS.filter((a) => a.regime === regime).map((a) => a.advertiser);
              return (
                <div
                  key={regime}
                  className="rounded-lg p-3"
                  style={{ background: 'var(--bg-secondary)', borderLeft: `3px solid ${style.tone}` }}
                >
                  <p className="text-xs font-semibold" style={{ color: style.tone }}>
                    {style.label}
                  </p>
                  <p className="mt-1 text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {style.note}
                  </p>
                  <p className="mt-1 text-[0.6875rem]" style={{ color: 'var(--text-muted)' }}>
                    {who.join(', ')}
                  </p>
                </div>
              );
            })}
          </div>
        </QueryState>
      </Section>

      <Section
        id="pacing"
        title="Efficacité par levier"
        provenance="Modèle sémantique — CTR %, Effective CPM (EUR). GRP volontairement absent."
        action={
          <button
            onClick={() => {
              const o = OPENERS.find((x) => x.id === 'pacing-live');
              if (o) ask(o);
            }}
            className="rounded-md px-2.5 py-1 text-xs font-medium"
            style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}
          >
            Interroger le pacing
          </button>
        }
      >
        <QueryState
          loading={channels.loading}
          error={channels.error}
          empty={!channels.loading && (channels.data ?? []).length === 0}
          onRetry={channels.reload}
        >
          <table className="w-full text-sm">
            <thead>
              <tr style={{ color: 'var(--text-muted)' }}>
                <th className="pb-2 text-left text-xs font-medium">Levier</th>
                <th className="pb-2 text-right text-xs font-medium">Diffusées</th>
                <th className="pb-2 text-right text-xs font-medium">CTR</th>
                <th className="pb-2 text-right text-xs font-medium">CPM effectif</th>
              </tr>
            </thead>
            <tbody>
              {(channels.data ?? []).map((c) => (
                <tr key={c.channel} style={{ color: 'var(--text-secondary)' }}>
                  <td className="py-1.5">
                    {c.channel}
                    <span className="ml-2 text-xs" style={{ color: 'var(--text-muted)' }}>
                      {c.group}
                    </span>
                  </td>
                  <td className="py-1.5 text-right tabular-nums">{fmtInt(c.delivered)}</td>
                  <td className="py-1.5 text-right tabular-nums">{fmtPct(c.ctr, 2)}</td>
                  <td className="py-1.5 text-right tabular-nums">{fmtEur(c.ecpm)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <p className="mt-3 text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            Le GRP n’apparaît pas dans ce tableau : ce n’est pas la même unité que l’impression
            et il n’existe que pour la TV, le DOOH et l’audio. Les additionner produirait un
            total parfaitement normal à l’écran et dénué de sens. Écart moyen affiché en
            {' '}
            {fmtDec(TOLERANCE, 0)} points de tolérance.
          </p>
        </QueryState>
      </Section>
    </>
  );
}
