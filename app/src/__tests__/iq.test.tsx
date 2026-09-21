import { describe, expect, it } from 'vitest';

import { IQ_REFERENCE } from '@/data/iqReference';
import { compareScopes, dependencyRows, scopeRows, scopeSummary } from '@/domain/iq';
import { mapIqDax } from '@/services/iqQueries';

describe('repository ontology reference', () => {
  it('compares identifiers, not just counts', () => {
    const [row] = IQ_REFERENCE.tabular.rows;
    expect(compareScopes([row], [{ ...row, campaignId: 'different' }]).equal).toBe(false);
    expect(compareScopes([row, row], [row]).equal).toBe(true);
    expect(scopeSummary([row, row])).toEqual({ campaigns: 1, advertisers: 1, markets: 1 });
  });

  it('independently generated paths agree for all owners and periods', () => {
    for (const owner of new Set(IQ_REFERENCE.tabular.rows.map((r) => r.mediaOwnerId))) {
      for (const quarter of ['2026-Q2', '2026-Q3']) {
        const left = scopeRows(IQ_REFERENCE.tabular.rows, owner, quarter);
        const right = scopeRows(IQ_REFERENCE.ontology.rows, owner, quarter);
        expect(left.length).toBeGreaterThan(0);
        expect(compareScopes(left, right).equal).toBe(true);
      }
    }
  });

  it('rejects missing fields and reads DAX aliases', () => {
    expect(() => dependencyRows([{ campaignId: 'one' }])).toThrow(/Missing dependency field/);
    const [row] = IQ_REFERENCE.tabular.rows;
    expect(mapIqDax([Object.fromEntries(Object.entries(row).map(([k, v]) => [`[${k}]`, v]))])).toEqual([row]);
  });
});
