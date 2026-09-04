/**
 * The deployed chain, declared once.
 *
 * The sibling console derives this from a live tenant probe and prints "8/8 components observed".
 * This one does not, and the difference is deliberate: a claim of observation that nothing
 * actually observed is worse than no claim at all. Every field below is a statement about what
 * was deployed, and the page says exactly that — nothing here reports a health check.
 *
 * `row` is data, not insertion order. The renderer places a node at `row` within its `layer`,
 * and the rows are chosen so no two hops cross: the analyst sits above the contract agent, and
 * the three stores it reads sit above the corpus the contract agent reads. In a picture whose
 * whole job is "who talks to what", a crossing reads as a wiring mistake.
 *
 * Nothing here invents an identifier. The corpus has no resource name printed because the one
 * thing it is guaranteed to be is the five master agreements, and that is what it says.
 */
export type Plane = 'foundry' | 'fabric' | 'semantic' | 'ontology';

export interface ChainNode {
  id: string;
  label: string;
  /** One line inside the box. Kept short — SVG text does not wrap, it collides. */
  detail: string;
  plane: Plane;
  layer: number;
  row: number;
  /** The long version, shown on hover and in the list under the diagram. */
  role: string;
}

export interface ChainEdge {
  from: string;
  to: string;
  /** How the hop is made. Printed in bold above the arrow. */
  protocol: string;
  /** What it carries, when the protocol alone is not enough. */
  short?: string;
}

export const CHAIN_NODES: ChainNode[] = [
  {
    id: 'supervisor',
    label: 'Zava-Media-Agent',
    detail: 'orchestration',
    plane: 'foundry',
    layer: 0,
    row: 0,
    role: 'Foundry supervisor. Dispatches the question and reconciles the two answers; computes nothing itself.',
  },
  {
    id: 'analyst',
    label: 'Zava_Media_Analyst',
    detail: 'data agent',
    plane: 'fabric',
    layer: 1,
    row: 0,
    role: 'Fabric data agent. Reads measures and traverses the graph. Holds no contractual term.',
  },
  {
    id: 'contracts',
    label: 'Zava-Media-Contracts',
    detail: 'contract agent',
    plane: 'foundry',
    layer: 1,
    row: 1,
    role: 'Cites the agreements and quotes the article. Computes nothing.',
  },
  {
    id: 'semantic',
    label: 'SM_Zava_Media',
    detail: '32 measures — every figure',
    plane: 'semantic',
    layer: 2,
    row: 0,
    role: 'Semantic model. The single definition of every figure the console prints.',
  },
  {
    id: 'ontology',
    label: 'ONT_Zava_Media',
    detail: '7 entities, 9 relationships',
    plane: 'ontology',
    layer: 2,
    row: 1,
    role: 'Ontology. Answers advertiser - brand - campaign - media owner by traversal, not by join.',
  },
  {
    id: 'realtime',
    label: 'RT_Zava_Media',
    detail: 'pacing events',
    plane: 'fabric',
    layer: 2,
    row: 2,
    role: 'Eventhouse. Pacing as it happens, attached to the campaign.',
  },
  {
    id: 'corpus',
    label: 'Master agreements',
    detail: 'ADV-001 to ADV-005',
    plane: 'foundry',
    layer: 2,
    row: 3,
    role: 'The five signed contracts, searched as text. No figure is stored here.',
  },
  {
    id: 'lakehouse',
    label: 'ZavaMediaLH',
    detail: '11 Delta tables',
    plane: 'fabric',
    layer: 3,
    row: 0,
    role: 'Lakehouse. One copy of the data, roughly 65,000 rows, read in place.',
  },
];

export const CHAIN_EDGES: ChainEdge[] = [
  { from: 'supervisor', to: 'analyst', protocol: 'A2A' },
  { from: 'supervisor', to: 'contracts', protocol: 'A2A' },
  { from: 'analyst', to: 'semantic', protocol: 'DAX' },
  { from: 'analyst', to: 'ontology', protocol: 'GQL' },
  { from: 'analyst', to: 'realtime', protocol: 'KQL' },
  { from: 'contracts', to: 'corpus', protocol: 'file_search' },
  { from: 'semantic', to: 'lakehouse', protocol: 'Direct Lake' },
  { from: 'ontology', to: 'lakehouse', protocol: 'Delta' },
];

export const PLANE_LABEL: Record<Plane, string> = {
  foundry: 'Foundry — orchestration',
  fabric: 'Fabric — data agent, stores',
  semantic: 'Semantic model (DAX)',
  ontology: 'Ontology (GQL)',
};
