import { dependencyRows, type DependencyRow } from '@/domain/iq';
import type { DaxRow } from './powerbi';

// COUNTROWS excludes combinations with no placement, without using delivery as a proxy for booking.
export const IQ_DEPENDENCIES_DAX = `EVALUATE
SELECTCOLUMNS(
  SUMMARIZECOLUMNS(
    dim_media_owner[media_owner_id], dim_media_owner[media_owner_name],
    dim_campaign[campaign_id], dim_campaign[campaign_name], dim_campaign[quarter],
    dim_advertiser[advertiser_id], dim_advertiser[advertiser_name],
    dim_market[market_id], dim_market[market_name],
    "Bookings", COUNTROWS(fact_plan)
  ),
  "mediaOwnerId", dim_media_owner[media_owner_id],
  "mediaOwner", dim_media_owner[media_owner_name],
  "campaignId", dim_campaign[campaign_id],
  "campaign", dim_campaign[campaign_name],
  "advertiserId", dim_advertiser[advertiser_id],
  "advertiser", dim_advertiser[advertiser_name],
  "marketId", dim_market[market_id],
  "market", dim_market[market_name],
  "quarter", dim_campaign[quarter]
)`;

export const IQ_DEPENDENCIES_GQL = `MATCH (owner:MediaOwner)<-[:CampaignBooksMediaOwner]-(campaign:Campaign)-[:CampaignForAdvertiser]->(advertiser:Advertiser),
      (campaign)-[:CampaignInMarket]->(market:Market)
RETURN DISTINCT
  owner.media_owner_id AS mediaOwnerId,
  owner.media_owner_name AS mediaOwner,
  campaign.campaign_id AS campaignId,
  campaign.campaign_name AS campaign,
  advertiser.advertiser_id AS advertiserId,
  advertiser.advertiser_name AS advertiser,
  market.market_id AS marketId,
  market.market_name AS market,
  campaign.quarter AS quarter`;

export function mapIqDax(rows: DaxRow[]): DependencyRow[] {
  return dependencyRows(rows.map((row) => Object.fromEntries(
    Object.entries(row).map(([key, value]) => [key.replace(/^\[|\]$/g, ''), value]),
  )));
}
