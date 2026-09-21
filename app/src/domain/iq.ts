export const IQ_QUESTION = 'Which clients and campaigns depend on this media owner?';

export type IqPath = 'tabular' | 'ontology';
export type IqMode = 'repository' | 'live';

export interface DependencyRow {
  mediaOwnerId: string;
  mediaOwner: string;
  campaignId: string;
  campaign: string;
  advertiserId: string;
  advertiser: string;
  marketId: string;
  market: string;
  quarter: string;
}

export interface IqRelation {
  name: string;
  from: string;
  to: string;
  table: string;
  fromKey: string;
  toKey: string;
}

export interface IqEvidence {
  rows: DependencyRow[];
  query: string;
  source: string;
  capturedAt: string;
}

export interface IqComparison {
  mode: IqMode;
  fingerprint: string;
  tabular: IqEvidence;
  ontology: IqEvidence;
}

export const ROW_FIELDS = [
  'mediaOwnerId', 'mediaOwner', 'campaignId', 'campaign',
  'advertiserId', 'advertiser', 'marketId', 'market', 'quarter',
] as const satisfies readonly (keyof DependencyRow)[];

/** Reject incomplete results rather than turning missing identifiers into an empty scope. */
export function dependencyRows(raw: unknown): DependencyRow[] {
  if (!Array.isArray(raw)) throw new Error('Expected dependency rows.');
  return raw.map((row: unknown) => {
    if (typeof row !== 'object' || row === null) throw new Error('Invalid dependency row.');
    const values = ROW_FIELDS.map((key) => {
      const value: unknown = Reflect.get(row, key);
      if (typeof value !== 'string' || !value.trim()) {
        throw new Error(`Missing dependency field: ${key}`);
      }
      return value;
    });
    const [mediaOwnerId, mediaOwner, campaignId, campaign, advertiserId, advertiser, marketId, market, quarter] = values;
    return { mediaOwnerId, mediaOwner, campaignId, campaign, advertiserId, advertiser, marketId, market, quarter };
  });
}

export function scopeRows(rows: DependencyRow[], ownerId: string, quarter: string): DependencyRow[] {
  return rows.filter((r) => r.mediaOwnerId === ownerId && r.quarter === quarter);
}

/** Membership equality, not matching counts: equal counts can conceal different campaigns. */
export function compareScopes(left: DependencyRow[], right: DependencyRow[]) {
  const key = (row: DependencyRow) =>
    JSON.stringify([row.mediaOwnerId, row.campaignId, row.advertiserId, row.marketId, row.quarter]);
  const l = new Set(left.map(key));
  const r = new Set(right.map(key));
  return {
    equal: l.size === r.size && [...l].every((id) => r.has(id)),
    onlyTabular: left.filter((row) => !r.has(key(row))),
    onlyOntology: right.filter((row) => !l.has(key(row))),
  };
}

export function scopeSummary(rows: DependencyRow[]) {
  return {
    campaigns: new Set(rows.map((r) => r.campaignId)).size,
    advertisers: new Set(rows.map((r) => r.advertiserId)).size,
    markets: new Set(rows.map((r) => r.marketId)).size,
  };
}

export function sharedAdvertisers(
  rows: DependencyRow[], ownerId: string, quarter: string, advertiserId: string,
): DependencyRow[] {
  return scopeRows(rows, ownerId, quarter).filter((r) => r.advertiserId !== advertiserId);
}

export function scopePrompt(
  owner: string, quarter: string, rows: DependencyRow[], mode: IqMode, capturedAt: string,
): string {
  if (rows.length === 0) throw new Error('Select a non-empty ontology scope before asking the agent.');
  const campaigns = [...new Set(rows.map((row) => row.campaignId))].sort();
  return [
    `For ${owner} in ${quarter}, explain which advertisers and campaigns depend on this media owner.`,
    `The application resolved the following campaign scope: ${campaigns.join(', ')}.`,
    mode === 'live'
      ? `This scope was read from the ontology graph at ${capturedAt}.`
      : 'This is a repository-data illustration, not a live observation. Verify the scope against the published ontology before using it.',
    'Confirm the scope through CampaignBooksMediaOwner, CampaignForAdvertiser and CampaignInMarket.',
    'If the current scope differs, say so explicitly rather than silently using the supplied list.',
    'Describe the shared dependencies. Booking a media owner is not evidence of a delivery failure or a contractual entitlement.',
    'Do not invent performance figures or infer contract terms. Name the source actually consulted.',
  ].join(' ');
}
