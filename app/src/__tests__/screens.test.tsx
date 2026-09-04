import { render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { AssistantProvider } from '@/components/AssistantProvider';
import { ContractsPage } from '@/pages/ContractsPage';
import { CoverPage } from '@/pages/CoverPage';
import { DiagnosticPage } from '@/pages/DiagnosticPage';
import { AGREEMENTS } from '@/data/contracts';
import { ALL_NAV, NAV, SECONDARY_NAV } from '@/domain/nav';
import { FOCUS_BY_FAMILY, SECTION_BY_FAMILY } from '@/domain/nav';
import { OPENERS, starters } from '@/domain/openers';

/**
 * Every figure in this app comes from the semantic model at render time, so a screen test
 * either mocks the transport or tests nothing. The stub returns an empty result set: what is
 * asserted here is that a screen mounts, states its own claim, and degrades honestly when the
 * model has nothing to say — never that it renders a particular number.
 */
vi.mock('@/services/powerbi', () => ({
  executeDax: vi.fn().mockResolvedValue([]),
  executeScalar: vi.fn().mockResolvedValue(null),
  semanticModelId: 'test-model',
  powerbiConfigured: true,
}));

function mount(ui: React.ReactElement) {
  return render(
    <MemoryRouter>
      <AssistantProvider>{ui}</AssistantProvider>
    </MemoryRouter>,
  );
}

/** A screen may say it has no data. It may never say `NaN`. */
function expectNoBrokenNumbers(container: HTMLElement) {
  expect(container.textContent ?? '').not.toMatch(/NaN|undefined|Infinity/);
}

describe('the cover', () => {
  it('offers a door to every section', () => {
    const { container } = mount(<CoverPage />);

    // A section absent from the cover is a section nobody finds.
    const reachable = new Set(starters(OPENERS).map((o) => o.family));
    expect(reachable.size).toBe(starters(OPENERS).length);

    expectNoBrokenNumbers(container);
  });

  it('shows a question, never an identifier', () => {
    mount(<CoverPage />);
    for (const o of starters(OPENERS)) {
      const label = screen.getAllByText(o.label);
      expect(label.length).toBeGreaterThan(0);
    }
  });
});

describe('the contract section', () => {
  it('names every agreement', () => {
    mount(<ContractsPage />);
    for (const a of AGREEMENTS) {
      expect(screen.getAllByText(new RegExp(a.advertiser)).length).toBeGreaterThan(0);
    }
  });

  /**
   * The load-bearing test of the whole demo.
   *
   * This screen exists to show that the entitlement is not in the warehouse. The moment someone
   * adds a KPI strip here to make the page look balanced, the argument collapses — and it would
   * collapse silently, because a page with numbers on it looks *better*.
   *
   * The assertion is structural rather than visual on purpose. The page does render digits —
   * "50%", "45 days", "art. 6.1" — but those are quoted clause terms, transcribed from the
   * contract corpus, not results. A regex over the rendered text cannot tell a quoted term from
   * a measurement, so it would either pass on a page full of KPIs or fail on faithful contract
   * language. What actually matters is the wiring: this module must never reach the semantic
   * model. If it does not import the query layer, it cannot display a measured figure.
   */
  it('never reaches the semantic model', () => {
    const src = readFileSync(
      join(process.cwd(), 'src', 'pages', 'ContractsPage.tsx'),
      'utf8',
    );
    expect(src).not.toMatch(/useDax|@\/data\/queries|executeDax|_DAX\b/);
  });
});

describe('the diagnostic', () => {
  /**
   * Rendered with no auth context on purpose: sign-in is the most likely broken link, and a
   * diagnostic that needs sign-in cannot report on sign-in. If this ever starts requiring the
   * auth provider, it has stopped being a diagnostic.
   */
  it('mounts outside the guard', () => {
    const { container } = render(
      <MemoryRouter>
        <DiagnosticPage />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Run the diagnostic/)).toBeTruthy();
    expectNoBrokenNumbers(container);
  });

  it('is absent from the navigation', () => {
    // Reachable by URL, never advertised: it is a repair tool, not a screen.
    expect(ALL_NAV.some((n) => n.to.includes('diagnostic'))).toBe(false);
  });
});

/**
 * Architecture was routed twice and linked from nowhere, and `WorkspaceLayout` — which titles
 * a page by looking it up in the nav manifest — rendered it with no heading at all. Both
 * failures were silent: the route resolved, the page mounted, and nothing said it was
 * unreachable. These two pin the fix rather than the symptom.
 */
describe('second-rank destinations', () => {
  it('are titled, so a page cannot render headless', () => {
    for (const entry of SECONDARY_NAV) {
      expect(ALL_NAV.find((n) => n.to === entry.to)?.label).toBeTruthy();
      expect(ALL_NAV.find((n) => n.to === entry.to)?.blurb).toBeTruthy();
    }
  });

  it('stay out of the four questions the console answers', () => {
    // Kept out of NAV so "every family lands on a listed section" keeps meaning what it says.
    const primary = new Set(NAV.map((n) => n.to));
    for (const entry of SECONDARY_NAV) expect(primary.has(entry.to)).toBe(false);
    for (const to of Object.values(SECTION_BY_FAMILY)) expect(primary.has(to)).toBe(true);
  });
});

/**
 * A focus anchor that matches no `Section id` scrolls nowhere and fails nothing. Pinned
 * against the ids the pages actually declare, read from source: the alternative is a typo
 * that only shows up as a card that quietly does not scroll.
 */
describe('focus anchors', () => {
  it('point at a section id that exists on the page they land on', () => {
    const fileFor: Record<string, string> = {
      '/portfolio': 'PortfolioPage.tsx',
      '/delivery': 'DeliveryPage.tsx',
      '/contracts': 'ContractsPage.tsx',
      '/billing': 'BillingPage.tsx',
    };

    for (const [family, anchor] of Object.entries(FOCUS_BY_FAMILY)) {
      const route = SECTION_BY_FAMILY[family as keyof typeof SECTION_BY_FAMILY];
      const src = readFileSync(join(process.cwd(), 'src', 'pages', fileFor[route]), 'utf8');
      expect(src).toMatch(new RegExp(`id="${anchor}"`));
    }
  });
});
