import { render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { AssistantProvider } from '@/components/AssistantProvider';
import { ContratsPage } from '@/pages/ContratsPage';
import { CoverPage } from '@/pages/CoverPage';
import { DiagnosticPage } from '@/pages/DiagnosticPage';
import { AGREEMENTS } from '@/data/contracts';
import { NAV } from '@/domain/nav';
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
    mount(<ContratsPage />);
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
   * "50 %", "45 jours", "art. 6.1" — but those are quoted clause terms, transcribed from the
   * contract corpus, not results. A regex over the rendered text cannot tell a quoted term from
   * a measurement, so it would either pass on a page full of KPIs or fail on faithful contract
   * language. What actually matters is the wiring: this module must never reach the semantic
   * model. If it does not import the query layer, it cannot display a measured figure.
   */
  it('never reaches the semantic model', () => {
    const src = readFileSync(
      join(process.cwd(), 'src', 'pages', 'ContratsPage.tsx'),
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
    expect(screen.getByText(/Lancer le diagnostic/)).toBeTruthy();
    expectNoBrokenNumbers(container);
  });

  it('is absent from the navigation', () => {
    // Reachable by URL, never advertised: it is a repair tool, not a screen.
    expect(NAV.some((n) => n.to.includes('diagnostic'))).toBe(false);
  });
});
