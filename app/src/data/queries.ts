/**
 * Every DAX query the app runs, in one file.
 *
 * Two rules hold this together:
 *
 * 1. **Bind to the model's measures, never re-derive them.** `[Delivery vs Plan %]`,
 *    `[Billing vs Spend Gap (EUR)]`, `[Net Spend (EUR)]` and the rest already exist in
 *    SM_Zava_Media and are what `Zava_Media_Report` and the data agent read. Writing an
 *    equivalent CALCULATE here would create a second definition of the same business rule,
 *    free to drift from the first — and drift only ever shows up as two screens disagreeing
 *    in front of a customer. That is the whole boundary rule of this demo, applied to the UI:
 *    Fabric computes, everything else reads.
 *
 * 2. **Keep the raw column keys here.** SUMMARIZECOLUMNS answers with keys like
 *    `dim_market[market_name]` and `[Delivery vs Plan %]`. Letting that spelling leak into
 *    components would scatter the coupling to the model across the UI; each query therefore
 *    ships with its own mapper and hands back a plain typed object.
 *
 * Measure names are copied from `fabric/powerbi/deploy_semantic_model.py`. A name invented
 * here does not fail loudly — `SUMMARIZECOLUMNS` errors, but a mistyped name inside a `ROW`
 * comes back as a blank cell that renders as a confident `0`.
 */
import type { DaxRow, DaxValue } from '@/services/powerbi';

const num = (v: DaxValue): number => (typeof v === 'number' ? v : Number(v ?? 0) || 0);
const str = (v: DaxValue): string => (v === null || v === undefined ? '' : String(v));

/* ------------------------------------------------------------------- Cover */

export interface CoverStats {
  campaigns: number;
  advertisers: number;
  markets: number;
  mediaOwners: number;
  over: number;
  under: number;
}

/**
 * The cover tiles. Counts come from the model rather than being typed into the page: a
 * hardcoded "80 campagnes" is a caption that keeps its value after the data changes, which is
 * exactly the kind of quiet lie this app exists not to tell.
 */
export const COVER_DAX = `
EVALUATE
ROW(
  "Campaigns", [Total Campaigns],
  "Advertisers", [Total Advertisers],
  "Markets", [Total Markets],
  "MediaOwners", [Total Media Owners],
  "Over", [Over-delivered Campaigns],
  "Under", [Under-delivered Campaigns]
)`;

export function mapCover(rows: DaxRow[]): CoverStats {
  const r = rows[0] ?? {};
  return {
    campaigns: num(r['[Campaigns]']),
    advertisers: num(r['[Advertisers]']),
    markets: num(r['[Markets]']),
    mediaOwners: num(r['[MediaOwners]']),
    over: num(r['[Over]']),
    under: num(r['[Under]']),
  };
}

/* ------------------------------------------------------------ Portefeuille */

export interface PortfolioKpis {
  campaigns: number;
  active: number;
  plannedBudget: number;
  netSpend: number;
  consumption: number;
  over: number;
  under: number;
  disputed: number;
  disputedAmount: number;
}

export const PORTFOLIO_DAX = `
EVALUATE
ROW(
  "Campaigns", [Total Campaigns],
  "Active", [Active Campaigns],
  "PlannedBudget", [Planned Budget (EUR)],
  "NetSpend", [Net Spend (EUR)],
  "Consumption", [Budget Consumption %],
  "Over", [Over-delivered Campaigns],
  "Under", [Under-delivered Campaigns],
  "Disputed", [Disputed Invoices],
  "DisputedAmount", [Disputed Amount (EUR)]
)`;

export function mapPortfolio(rows: DaxRow[]): PortfolioKpis {
  const r = rows[0] ?? {};
  return {
    campaigns: num(r['[Campaigns]']),
    active: num(r['[Active]']),
    plannedBudget: num(r['[PlannedBudget]']),
    netSpend: num(r['[NetSpend]']),
    consumption: num(r['[Consumption]']),
    over: num(r['[Over]']),
    under: num(r['[Under]']),
    disputed: num(r['[Disputed]']),
    disputedAmount: num(r['[DisputedAmount]']),
  };
}

/* ---------------------------------------------------------------- Livraison */

export interface MarketVariance {
  advertiser: string;
  market: string;
  quarter: string;
  planned: number;
  delivered: number;
  variance: number;
  gap: number;
}

/**
 * The variance table, and the one query the demo turns on.
 *
 * No advertiser and no market is named in it. The three cases that matter have to *emerge*
 * from the same ranking as everything else — naming them here would turn a finding into a
 * lookup, and the room can tell the difference.
 *
 * `[Delivery vs Plan %]` is signed: over-delivery is positive, under-delivery negative. The
 * page must not take an absolute value anywhere, because the sign is what selects the
 * contractual regime.
 */
export const VARIANCE_DAX = `
EVALUATE
SUMMARIZECOLUMNS(
  dim_advertiser[advertiser_name],
  dim_market[market_name],
  dim_campaign[quarter],
  "Planned", [Planned Impressions],
  "Delivered", [Delivered Impressions],
  "Variance", [Delivery vs Plan %],
  "Gap", [Impression Gap]
)
ORDER BY [Variance] DESC`;

export function mapVariance(rows: DaxRow[]): MarketVariance[] {
  return rows
    .map((r) => ({
      advertiser: str(r['dim_advertiser[advertiser_name]']),
      market: str(r['dim_market[market_name]']),
      quarter: str(r['dim_campaign[quarter]']),
      planned: num(r['[Planned]']),
      delivered: num(r['[Delivered]']),
      variance: num(r['[Variance]']),
      gap: num(r['[Gap]']),
    }))
    .filter((v) => v.advertiser !== '' && v.market !== '');
}

export interface ChannelEfficiency {
  channel: string;
  group: string;
  delivered: number;
  clicks: number;
  ctr: number;
  ecpm: number;
}

/**
 * GRP is deliberately absent from this query.
 *
 * GRP and impressions are different units and must never be added or ranked together; the
 * model only carries GRP for the channels where `dim_channel[is_grp_channel]` is true. A
 * single table mixing both would be arithmetically meaningless and would look perfectly
 * normal on screen.
 */
export const CHANNEL_DAX = `
EVALUATE
SUMMARIZECOLUMNS(
  dim_channel[channel_name],
  dim_channel[channel_group],
  "Delivered", [Delivered Impressions],
  "Clicks", [Delivered Clicks],
  "CTR", [CTR %],
  "ECPM", [Effective CPM (EUR)]
)
ORDER BY [Delivered] DESC`;

export function mapChannels(rows: DaxRow[]): ChannelEfficiency[] {
  return rows
    .map((r) => ({
      channel: str(r['dim_channel[channel_name]']),
      group: str(r['dim_channel[channel_group]']),
      delivered: num(r['[Delivered]']),
      clicks: num(r['[Clicks]']),
      ctr: num(r['[CTR]']),
      ecpm: num(r['[ECPM]']),
    }))
    .filter((c) => c.channel !== '');
}

/* ------------------------------------------------------------- Facturation */

export interface BillingGap {
  advertiser: string;
  market: string;
  netSpend: number;
  netBilled: number;
  gap: number;
}

/**
 * Delivered against billed, per advertiser and market.
 *
 * `[Billing vs Spend Gap (EUR)]` is the measure the report reads, so the app cannot quietly
 * disagree with the report about how much money is unbilled.
 */
export const BILLING_DAX = `
EVALUATE
SUMMARIZECOLUMNS(
  dim_advertiser[advertiser_name],
  dim_market[market_name],
  "NetSpend", [Net Spend (EUR)],
  "NetBilled", [Net Billed (EUR)],
  "Gap", [Billing vs Spend Gap (EUR)]
)
ORDER BY [Gap] DESC`;

export function mapBilling(rows: DaxRow[]): BillingGap[] {
  return rows
    .map((r) => ({
      advertiser: str(r['dim_advertiser[advertiser_name]']),
      market: str(r['dim_market[market_name]']),
      netSpend: num(r['[NetSpend]']),
      netBilled: num(r['[NetBilled]']),
      gap: num(r['[Gap]']),
    }))
    .filter((b) => b.advertiser !== '');
}

export interface RebateRow {
  mediaOwner: string;
  gross: number;
  rebate: number;
  netNet: number;
  rebatePct: number;
}

/**
 * `dim_media_owner[rebate_pct]` is what the media owner grants the **agency**. It is not what
 * the agency owes the advertiser, and the panel that renders this must say so in words.
 *
 * That confusion is not hypothetical: it is the single most expensive misreading available in
 * this dataset, and the data agent's own instructions carry the same warning.
 */
export const REBATE_DAX = `
EVALUATE
SUMMARIZECOLUMNS(
  dim_media_owner[media_owner_name],
  "Gross", [Gross Billed (EUR)],
  "Rebate", [Rebate Amount (EUR)],
  "NetNet", [Net Net Billed (EUR)],
  "RebatePct", [Rebate % of Gross]
)
ORDER BY [Gross] DESC`;

export function mapRebates(rows: DaxRow[]): RebateRow[] {
  return rows
    .map((r) => ({
      mediaOwner: str(r['dim_media_owner[media_owner_name]']),
      gross: num(r['[Gross]']),
      rebate: num(r['[Rebate]']),
      netNet: num(r['[NetNet]']),
      rebatePct: num(r['[RebatePct]']),
    }))
    .filter((r) => r.mediaOwner !== '');
}

export interface BillingTotals {
  gross: number;
  net: number;
  netNet: number;
  invoices: number;
  disputed: number;
  disputedAmount: number;
  gap: number;
}

/** The billing header, at portfolio grain. Every field is a measure the report also reads. */
export const BILLING_TOTALS_DAX = `
EVALUATE
ROW(
  "Gross", [Gross Billed (EUR)],
  "Net", [Net Billed (EUR)],
  "NetNet", [Net Net Billed (EUR)],
  "Invoices", [Total Invoices],
  "Disputed", [Disputed Invoices],
  "DisputedAmount", [Disputed Amount (EUR)],
  "Gap", [Billing vs Spend Gap (EUR)]
)`;

export function mapBillingTotals(rows: DaxRow[]): BillingTotals {
  const r = rows[0] ?? {};
  return {
    gross: num(r['[Gross]']),
    net: num(r['[Net]']),
    netNet: num(r['[NetNet]']),
    invoices: num(r['[Invoices]']),
    disputed: num(r['[Disputed]']),
    disputedAmount: num(r['[DisputedAmount]']),
    gap: num(r['[Gap]']),
  };
}

/**
 * The grain panel.
 *
 * Two campaigns were never billed, and six rows are missing from the billing fact, because
 * that table is grained campaign x media owner and each of those campaigns was sold by three
 * owners. Both numbers are correct; they answer different questions.
 *
 * The query groups at the **finer** of the two grains and lets the page derive the coarser one
 * by collapsing on campaign. Asking the model for the two counts separately would let them
 * drift apart, which is precisely the failure the panel exists to make visible.
 *
 * Campaign x media owner is also the only grain available here: the billing fact has no
 * relationship to the date table, so slicing this by month would silently leave billing
 * unfiltered while spend was filtered — a gap that grows with every month added.
 */
export const GRAIN_DAX = `
EVALUATE
SUMMARIZECOLUMNS(
  dim_campaign[campaign_id],
  dim_campaign[campaign_name],
  dim_media_owner[media_owner_name],
  "NetSpend", [Net Spend (EUR)],
  "NetBilled", [Net Billed (EUR)]
)`;

export interface GrainStats {
  /** Missing rows at campaign x media owner grain. */
  rows: number;
  /** Distinct campaigns behind those rows. */
  campaigns: number;
  /** Net spend carried by them. */
  amount: number;
  names: string[];
}

export function mapGrain(rows: DaxRow[]): GrainStats {
  const unbilled = rows
    .map((r) => ({
      id: str(r['dim_campaign[campaign_id]']),
      name: str(r['dim_campaign[campaign_name]']),
      spend: num(r['[NetSpend]']),
      billed: num(r['[NetBilled]']),
    }))
    .filter((r) => r.id !== '' && r.spend > 0 && r.billed === 0);

  const byCampaign = new Map(unbilled.map((r) => [r.id, r.name]));

  return {
    rows: unbilled.length,
    campaigns: byCampaign.size,
    amount: unbilled.reduce((sum, r) => sum + r.spend, 0),
    names: [...byCampaign.values()],
  };
}
