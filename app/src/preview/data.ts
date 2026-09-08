import {
  BILLING_DAX, BILLING_TOTALS_DAX, CHANNEL_DAX, COVER_DAX, GRAIN_DAX,
  PORTFOLIO_DAX, REBATE_DAX, VARIANCE_DAX,
} from '@/data/queries';
import type { QuerySource } from '@/data/querySource';
import type { DaxRow } from '@/services/powerbi';

// Illustrative layout fixtures, not a snapshot of Fabric and never a live-error fallback.
const rowsByQuery = new Map<string, DaxRow[]>([
  [COVER_DAX, [{
    '[Campaigns]': 80, '[Advertisers]': 5, '[Markets]': 4,
    '[MediaOwners]': 9, '[Over]': 4, '[Under]': 2,
  }]],
  [PORTFOLIO_DAX, [{
    '[Campaigns]': 80, '[Active]': 40, '[PlannedBudget]': 25000000,
    '[NetSpend]': 20000000, '[Consumption]': 0.8, '[Over]': 4, '[Under]': 2,
    '[Disputed]': null, '[DisputedAmount]': null,
  }]],
  [VARIANCE_DAX, [
    {
      'dim_advertiser[advertiser_name]': 'Contoso Mobility',
      'dim_market[market_name]': 'Spain', 'dim_campaign[quarter]': '2026-Q3',
      '[Planned]': 100000000, '[Delivered]': 112000000, '[Variance]': 0.12, '[Gap]': 12000000,
    },
    {
      'dim_advertiser[advertiser_name]': 'Litware Retail',
      'dim_market[market_name]': 'United Kingdom', 'dim_campaign[quarter]': '2026-Q3',
      '[Planned]': 100000000, '[Delivered]': 111000000, '[Variance]': 0.11, '[Gap]': 11000000,
    },
    {
      'dim_advertiser[advertiser_name]': 'Fabrikam Beauty',
      'dim_market[market_name]': 'Italy', 'dim_campaign[quarter]': '2026-Q3',
      '[Planned]': 100000000, '[Delivered]': 92000000, '[Variance]': -0.08, '[Gap]': -8000000,
    },
  ]],
  [CHANNEL_DAX, [{
    'dim_channel[channel_name]': 'Display', 'dim_channel[channel_group]': 'Digital',
    '[Delivered]': 40000000, '[Clicks]': 200000, '[CTR]': 0.005, '[ECPM]': 6,
  }]],
  [BILLING_DAX, [{
    'dim_advertiser[advertiser_name]': 'Northwind Foods',
    'dim_market[market_name]': 'France',
    '[NetSpend]': 3000000, '[NetBilled]': 2700000, '[Gap]': 300000,
  }]],
  [BILLING_TOTALS_DAX, [{
    '[Gross]': 22000000, '[Net]': 19700000, '[NetNet]': 18600000,
    '[Invoices]': 657, '[Disputed]': null, '[DisputedAmount]': null, '[Gap]': 300000,
  }]],
  [REBATE_DAX, [{
    'dim_media_owner[media_owner_name]': 'Example media owner',
    '[Gross]': 22000000, '[Rebate]': 1100000, '[NetNet]': 18600000, '[RebatePct]': 0.05,
  }]],
  [GRAIN_DAX, [{
    'dim_campaign[campaign_id]': 'preview-campaign',
    'dim_campaign[campaign_name]': 'Northwind France',
    'dim_media_owner[media_owner_name]': 'Example media owner',
    '[NetSpend]': 3000000, '[NetBilled]': 2700000,
  }]],
]);

export const previewSource: QuerySource = {
  preview: true,
  async execute(dax) {
    const rows = rowsByQuery.get(dax);
    if (!rows) throw new Error('No design-preview data is defined for this query.');
    return rows.map((row) => ({ ...row }));
  },
};
