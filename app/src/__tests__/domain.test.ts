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
    expect(basePath('/preview/livraison')).toBe('/preview');
    expect(basePath('/livraison')).toBe('');
  });
});
