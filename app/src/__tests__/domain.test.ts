import { describe, expect, it } from 'vitest';

import * as queries from '@/data/queries';
import {
  FOCUS_BY_FAMILY,
  NAV,
  SECTION_BY_FAMILY,
  basePath,
  routeForFamily,
} from '@/domain/nav';
import { HOUSE_STYLE, OPENERS, followUps, selectOpeners, starters } from '@/domain/openers';
import type { OpenerFamily } from '@/domain/openers';

/**
 * The 32 measures the semantic model actually carries.
 *
 * Pinned here because an invented measure name does not fail loudly: inside a `ROW(...)` it
 * comes back as an empty cell and renders as a confident zero. The only place that can be
 * caught cheaply is here, against the list the deployment script writes.
 */
const MEASURES = [
  'Total Advertisers',
  'Total Brands',
  'Total Campaigns',
  'Active Campaigns',
  'Total Markets',
  'Total Channels',
  'Total Media Owners',
  'Planned Budget (EUR)',
  'Planned Impressions',
  'Planned GRP',
  'Delivered Impressions',
  'Delivered Clicks',
  'Net Spend (EUR)',
  'Delivered GRP',
  'CTR %',
  'Effective CPM (EUR)',
  'Delivery vs Plan %',
  'Delivery Ratio',
  'Impression Gap',
  'GRP Delivery %',
  'Over-delivered Campaigns',
  'Under-delivered Campaigns',
  'Budget Consumption %',
  'Gross Billed (EUR)',
  'Net Billed (EUR)',
  'Rebate Amount (EUR)',
  'Net Net Billed (EUR)',
  'Rebate % of Gross',
  'Total Invoices',
  'Disputed Invoices',
  'Disputed Amount (EUR)',
  'Billing vs Spend Gap (EUR)',
];

/** Every `[Bracketed Name]` in a query that is not a result-column alias. */
function measuresCited(dax: string): string[] {
  const cited = dax.match(/\[[A-Z][A-Za-z0-9 %()/.-]*\]/g) ?? [];
  return [...new Set(cited.map((m) => m.slice(1, -1)))];
}

const DAX_QUERIES = Object.entries(queries).filter(
  ([name, value]) => name.endsWith('_DAX') && typeof value === 'string',
) as [string, string][];

describe('queries', () => {
  it('cites only measures the model carries', () => {
    expect(DAX_QUERIES.length).toBeGreaterThan(0);

    for (const [name, dax] of DAX_QUERIES) {
      for (const cited of measuresCited(dax)) {
        // Aliases introduced by the query itself are read back at `[Alias]`, so they are
        // legitimate; anything else must exist in the model.
        const isAlias = new RegExp(`"${cited}"\\s*,`).test(dax);
        if (isAlias) continue;
        expect(MEASURES, `${name} cites an unknown measure: ${cited}`).toContain(cited);
      }
    }
  });

  it('never asks for GRP and impressions in the same total', () => {
    // Different units. Summing them produces a perfectly normal-looking number and no error.
    for (const [name, dax] of DAX_QUERIES) {
      const grp = /GRP/.test(dax);
      const impressions = /Impressions/.test(dax);
      if (grp && impressions) {
        expect(
          /SUMMARIZECOLUMNS/.test(dax),
          `${name} mixes GRP and impressions outside a grouped result`,
        ).toBe(true);
      }
    }
  });
});

describe('the question registry', () => {
  it('covers every family before it caps the list', () => {
    // A cap applied to an ordered list does not sample it, it truncates it: the graph
    // questions sit at the end of the registry, so `slice(0, 3)` on the raw list would make
    // the ontology unreachable without raising anything.
    const families = new Set(OPENERS.map((o) => o.family));
    const selected = new Set(selectOpeners(OPENERS).map((o) => o.family));
    expect(selected).toEqual(families);
  });

  it('keeps a crossing question in the opening three', () => {
    // The whole argument of the demo is a question neither system can answer alone. If the
    // first three cards are all single-source, the room never sees it.
    expect(starters(OPENERS).some((o) => o.kind === 'mixed')).toBe(true);
  });

  it('never shows an identifier in a label', () => {
    // The prompt names tables and columns because the agent needs them. The label is what a
    // person reads, and a table name in it turns a question into a query.
    for (const o of OPENERS) {
      expect(o.label, `${o.id} names a table`).not.toMatch(/\b(?:dim|fact)_[a-z_]+\b/);
      expect(o.label, `${o.id} contains a bracketed identifier`).not.toMatch(/\[.+\]/);
    }
  });

  it('shares one house style rather than six copies of it', () => {
    for (const o of OPENERS) {
      expect(o.prompt, `${o.id} does not carry the house style`).toContain(HOUSE_STYLE.trim());
    }
  });

  it('drops questions already asked from the follow-ups', () => {
    const first = OPENERS[0];
    const rest = followUps([first.id]);
    expect(rest.some((o) => o.id === first.id)).toBe(false);
    expect(rest.length).toBeLessThanOrEqual(3);
  });
});

describe('the route manifest', () => {
  it('lists each section exactly once', () => {
    const paths = NAV.map((n) => n.to);
    expect(new Set(paths).size).toBe(paths.length);
  });

  it('sends every family to a listed section', () => {
    // A family pointing at a route the nav does not carry strands the question: the card
    // navigates, the rail highlights nothing, and the reader cannot get back.
    for (const family of Object.keys(SECTION_BY_FAMILY) as OpenerFamily[]) {
      expect(NAV.map((n) => n.to)).toContain(routeForFamily(family));
    }
  });

  it('gives every family a focus anchor', () => {
    for (const family of Object.keys(SECTION_BY_FAMILY) as OpenerFamily[]) {
      expect(FOCUS_BY_FAMILY[family]).toBeTruthy();
    }
  });

  it('keeps preview navigation inside the preview mount', () => {
    // A bare jump out of `/preview` lands on a guarded route and bounces to sign-in.
    expect(basePath('/preview/delivery')).toBe('/preview');
    expect(basePath('/delivery')).toBe('');
  });
});

/**
 * The grain panel carries the punchline of the billing section, and it had no coverage at all
 * until a shipped `billed === 0` filter matched nothing against the deployed model and drew an
 * empty panel underneath a header still reporting the gap.
 *
 * These rows are transcribed from the deployed semantic model, not invented: the six real
 * shortfall rows and two of the balanced ones. Pinning them here means a future change to the
 * filter has to survive the shape the data actually has.
 */
describe('the grain panel', () => {
  const row = (id: string, name: string, owner: string, spend: number, billed: number) => ({
    'dim_campaign[campaign_id]': id,
    'dim_campaign[campaign_name]': name,
    'dim_media_owner[media_owner_name]': owner,
    '[NetSpend]': spend,
    '[NetBilled]': billed,
  });

  const FASHION = 'Litware Fashion GB 2026-Q3 Performance';
  const HOME = 'Litware Home GB 2026-Q3 Loyalty';

  const DEPLOYED = [
    row('CMP-0072', FASHION, 'Kestrel Retail Media', 584116.22, 393829.17),
    row('CMP-0072', FASHION, 'Halcyon Social', 476343.01, 320104.68),
    row('CMP-0072', FASHION, 'Solstice Audio', 267354, 179703.25),
    row('CMP-0068', HOME, 'Alpine Digital', 254904.76, 170363.77),
    row('CMP-0068', HOME, 'Halcyon Social', 216646.43, 145535.21),
    row('CMP-0068', HOME, 'Meridian TV', 179266.12, 119935.93),
    row('CMP-0037', 'Adventure Works Breaks DE 2026-Q2 Awareness', 'Alpine Digital', 551053.48, 551053.48),
    row('CMP-0041', 'Contoso Fleet ES 2026-Q3 Performance', 'Vertex Outdoor', 392204.35, 392204.35),
  ];

  it('finds the six under-billed rows across two campaigns', () => {
    const g = queries.mapGrain(DEPLOYED);
    expect(g.rows).toBe(6);
    expect(g.campaigns).toBe(2);
    expect(g.names).toEqual(expect.arrayContaining([FASHION, HOME]));
  });

  it('reports the shortfall, not the spend', () => {
    // Summing spend would report 1.98M EUR of "unbilled" money that was in fact largely
    // invoiced. The panel has to answer with what is missing: 649,158.53 EUR.
    expect(queries.mapGrain(DEPLOYED).amount).toBeCloseTo(649158.53, 2);
  });

  it('does not read rounding noise as an anomaly', () => {
    const noisy = [row('CMP-0037', 'Balanced', 'Alpine Digital', 551053.48, 551053.47)];
    expect(queries.mapGrain(noisy).rows).toBe(0);
  });

  it('ignores rows with no campaign key', () => {
    const orphan = [row('', 'Unattributed', 'Alpine Digital', 100000, 0)];
    expect(queries.mapGrain(orphan).rows).toBe(0);
  });
});

/**
 * The deployed model carries no disputed invoice, so `[Disputed Invoices]` answers blank. Folded
 * to `0` that becomes a claim — "we checked, there are none" — indistinguishable from a query
 * that returned nothing. The mapper keeps the blank so the card can name which one it is.
 */
describe('a measure that answers blank', () => {
  it('keeps the blank apart from a real zero', () => {
    const blank = queries.mapBillingTotals([
      { '[Gross]': 70290759.57, '[Net]': 60885308.41, '[Disputed]': null, '[DisputedAmount]': null },
    ]);
    expect(blank.disputed).toBeNull();
    expect(blank.disputedAmount).toBeNull();

    const zero = queries.mapBillingTotals([{ '[Disputed]': 0, '[DisputedAmount]': 0 }]);
    expect(zero.disputed).toBe(0);
  });

  it('still folds the measures that have no such claim', () => {
    // A blank total is genuinely zero money; only the counts that assert an absence are kept.
    expect(queries.mapBillingTotals([{ '[Gross]': null }]).gross).toBe(0);
  });
});
