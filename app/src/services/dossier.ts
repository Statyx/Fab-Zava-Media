import reference from '@/data/iq-dossier-reference.generated.json';
import webContext from '@/data/iq-web-context.generated.json';
import workContext from '@/data/iq-work-context.generated.json';
import { checkContractEvidence, dossierPrompt, type DossierCapture, type DossierCase, type DossierInput, type WebContext, type WorkContext } from '@/domain/dossier';
import { executeDax, semanticModelId } from './powerbi';
import { FABRIC_SCOPES, getToken } from './msal';
import { askSupervisor } from './foundryAgent';

export const DOSSIER_REFERENCE: DossierInput = reference;
export const DOSSIER_WEB_CONTEXT: WebContext = webContext;
export const DOSSIER_WORK_CONTEXT: WorkContext = workContext;

const captureFiles = import.meta.glob('../data/iq-dossier-capture.generated.json', { eager: true, import: 'default' });

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function validateCapture(raw: unknown, input = DOSSIER_REFERENCE): DossierCapture {
  if (!object(raw) || raw.fingerprint !== input.fingerprint ||
      raw.scenarioId !== input.scenarioId || raw.asOf !== input.asOf || !Array.isArray(raw.cases)) {
    throw new Error('Recorded evidence does not match this scenario and its source fingerprint.');
  }
  const records = raw.cases;
  const cases = input.cases.map((item) => {
    const record = records.find((c: unknown) => object(c) && c.id === item.id);
    if (!object(record) || record.prompt !== dossierPrompt(item, input.asOf) ||
        typeof record.text !== 'string' || !record.text.trim() ||
        typeof record.capturedAt !== 'string' || !Number.isFinite(Date.parse(record.capturedAt)) ||
        typeof record.seconds !== 'number' || !Number.isFinite(record.seconds) || record.seconds < 0 ||
        !Array.isArray(record.toolsFired) || !record.toolsFired.length || record.toolsFired.some((t: unknown) => typeof t !== 'string') ||
        !Array.isArray(record.citations) || !object(record.facts) ||
        !Array.isArray(record.campaignIds) || record.campaignIds.some((id: unknown) => typeof id !== 'string') ||
        typeof record.dax !== 'string' || !record.dax.trim() || typeof record.gql !== 'string' || !record.gql.trim()) {
      throw new Error(`Complete recorded evidence is not available for ${item.advertiser}.`);
    }
    const facts = validateFacts(record.facts);
    const grounding = checkContractEvidence(item, { text: record.text, toolsFired: record.toolsFired });
    if (grounding.status !== 'confirmed') throw new Error(`${item.advertiser}: ${grounding.reason}`);
    if (facts.planned !== item.facts.planned || facts.delivered !== item.facts.delivered ||
        Math.abs(facts.variance - item.facts.variance) > 0.0005 ||
        [...new Set(record.campaignIds)].sort().join('|') !== [...item.campaignIds].sort().join('|')) {
      throw new Error(`Recorded figures or scope differ from the prepared ${item.advertiser} case.`);
    }
    const citations = record.citations.map((citation: unknown) => {
      if (!object(citation) || typeof citation.label !== 'string' ||
          (citation.detail !== undefined && typeof citation.detail !== 'string')) {
        throw new Error('Invalid recorded citation.');
      }
      return { label: citation.label, detail: citation.detail };
    });
    return {
      id: item.id, prompt: record.prompt, capturedAt: record.capturedAt, seconds: record.seconds,
      text: record.text, toolsFired: record.toolsFired, citations, facts,
      campaignIds: record.campaignIds, dax: record.dax, gql: record.gql,
    };
  });
  return { fingerprint: input.fingerprint, scenarioId: input.scenarioId, asOf: input.asOf, cases };
}

export function recordedDossiers(): { capture: DossierCapture | null; error: string | null } {
  const [raw] = Object.values(captureFiles);
  if (!raw) return { capture: null, error: 'Prepared Fabric/Foundry evidence is not yet available for this scenario.' };
  try {
    return { capture: validateCapture(raw), error: null };
  } catch (err) {
    return { capture: null, error: err instanceof Error ? err.message : String(err) };
  }
}

export function validateFacts(raw: Record<string, unknown>): DossierCase['facts'] {
  const { planned, delivered, variance } = raw;
  if (typeof planned !== 'number' || !Number.isFinite(planned) || planned <= 0 ||
      typeof delivered !== 'number' || !Number.isFinite(delivered) || delivered < 0 ||
      typeof variance !== 'number' || !Number.isFinite(variance) ||
      Math.abs(delivered / planned - 1 - variance) > 0.0005) {
    throw new Error('The measured figures are missing or inconsistent.');
  }
  return { planned, delivered, variance };
}

const quoted = (text: string) => `"${text.replaceAll('"', '""')}"`;
export function dossierDax(item: DossierCase): string {
  return `EVALUATE CALCULATETABLE(
  ROW("planned", [Planned Impressions], "delivered", [Delivered Impressions], "variance", [Delivery vs Plan %]),
  dim_advertiser[advertiser_id] = ${quoted(item.advertiserId)},
  dim_market[market_id] = ${quoted(item.marketId)},
  dim_campaign[quarter] = ${quoted(item.quarter)}
)`;
}

export async function readLiveDossier(item: DossierCase, onProgress: (text: string) => void) {
  const started = performance.now();
  const workspace = import.meta.env.VITE_ZAVA_WORKSPACE_ID;
  const graph = import.meta.env.VITE_ZAVA_GRAPH_MODEL_ID;
  if (!workspace || !graph || !semanticModelId) {
    throw new Error('Live dossier evidence requires the Zava workspace, graph model and semantic model configuration.');
  }
  onProgress('Reading the measured figures…');
  const dax = dossierDax(item);
  const result = await executeDax(dax);
  if (result.length !== 1) throw new Error('Expected a single row of scoped measurements.');
  const facts = validateFacts({
    planned: result[0]['[planned]'], delivered: result[0]['[delivered]'], variance: result[0]['[variance]'],
  });
  // Only identifiers from the fixed scenario manifest are used in this query.
  const ids = [item.advertiserId, item.marketId, item.quarter];
  if (ids.some((id) => !/^[A-Za-z0-9-]+$/.test(id))) throw new Error('Invalid scenario identifier.');
  const gql = `MATCH (c:Campaign)-[:CampaignForAdvertiser]->(a:Advertiser), (c)-[:CampaignInMarket]->(m:Market)
WHERE a.advertiser_id = '${item.advertiserId}' AND m.market_id = '${item.marketId}' AND c.quarter = '${item.quarter}'
RETURN DISTINCT c.campaign_id AS campaignId`;
  onProgress('Reading the existing ontology graph…');
  const token = await getToken(FABRIC_SCOPES, false);
  const response = await fetch(
    `https://api.fabric.microsoft.com/v1/workspaces/${encodeURIComponent(workspace)}/graphModels/${encodeURIComponent(graph)}/executeQuery?beta=true`,
    {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: gql }),
      signal: AbortSignal.timeout(120_000),
    },
  );
  if (!response.ok) throw new Error(`Graph query failed (${response.status}).`);
  const body: unknown = await response.json();
  const campaignIds = graphCampaignIds(body);
  if (campaignIds.join('|') !== [...item.campaignIds].sort().join('|')) {
    throw new Error('The live graph scope differs from the prepared case. Review the evidence before using this scenario.');
  }
  if (facts.planned !== item.facts.planned || facts.delivered !== item.facts.delivered ||
      Math.abs(facts.variance - item.facts.variance) > 0.0005) {
    throw new Error('Live figures differ from the prepared scenario. Refresh and review the dossier evidence first.');
  }
  onProgress('Reading the signed agreement through Foundry…');
  const answer = await askSupervisor(dossierPrompt(item, DOSSIER_REFERENCE.asOf), onProgress);
  if (!answer.text.trim() || !answer.toolsFired.length) throw new Error('Foundry returned no sourced answer for this dossier.');
  return {
    id: item.id, prompt: dossierPrompt(item, DOSSIER_REFERENCE.asOf),
    capturedAt: new Date().toISOString(), seconds: (performance.now() - started) / 1000,
    text: answer.text, toolsFired: answer.toolsFired, citations: answer.citations,
    facts, campaignIds, dax, gql,
  };
}

export function graphCampaignIds(raw: unknown): string[] {
  if (!object(raw) || !object(raw.status) || raw.status.code !== '00000' ||
      !object(raw.result) || raw.result.kind !== 'TABLE' || !Array.isArray(raw.result.data)) {
    throw new Error('The graph did not return a successful table result.');
  }
  const ids = raw.result.data.map((row: unknown) => {
    if (!object(row) || typeof row.campaignId !== 'string' || !row.campaignId) {
      throw new Error('The graph returned a missing campaign identifier.');
    }
    return row.campaignId;
  });
  return [...new Set(ids)].sort();
}
