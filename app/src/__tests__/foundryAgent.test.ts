/**
 * The supervisor's reply is not a string, it is a list of everything that happened during the
 * run, and reading it wrong does not raise — it renders.
 *
 * Both cases pinned here were observed against the live agent, not imagined:
 *
 *  - a run came back with two `message` items, a draft and the rewrite that followed a second
 *    hop to the contracts agent. Joining them put two ninety-word answers and two `### SOURCE`
 *    blocks on screen, against a prompt that asks for one of each;
 *  - `mcp_list_tools` reports `server_label: "fabricdataagent"` on *every* run, including runs
 *    where the data agent was never consulted. Counting it credits Fabric for an answer that
 *    came entirely out of the contracts, which is exactly the false provenance this console
 *    exists to disprove.
 *
 * The fixtures are trimmed shapes of real payloads: the fields the parsers read, and the
 * ordering they came in.
 */
import { describe, expect, it } from 'vitest';

import { NOT_A_SOURCE, SOURCE_LABEL } from '@/components/AssistantRail';
import { collectTools, readText } from '@/services/foundryAgent';

const message = (text: string) => ({
  type: 'message',
  role: 'assistant',
  content: [{ type: 'output_text', text }],
});

describe('reading the supervisor answer', () => {
  it('keeps the rewrite and drops the draft', () => {
    const output = [
      { type: 'mcp_list_tools', server_label: 'fabricdataagent' },
      message('The gap is €65,000.\n\n### SOURCE\nfirst pass'),
      { type: 'a2a_preview_call', name: 'zava-media-contracts-a2a' },
      { type: 'a2a_preview_call_output', name: 'zava-media-contracts-a2a' },
      message('The gap is €65,000, claimable for 90 days.\n\n### SOURCE\nsecond pass'),
    ];

    const text = readText(output);
    expect(text).toContain('90 days');
    expect(text).not.toContain('first pass');
    expect(text.match(/### SOURCE/g)).toHaveLength(1);
  });

  it('joins the blocks of the answer it keeps', () => {
    // Parts of one reply, not competing versions of it: dropping all but the last would
    // truncate the answer at its `### SOURCE` block.
    const output = [
      {
        type: 'message',
        content: [{ type: 'output_text', text: 'Conclusion.' }, { type: 'output_text', text: '### SOURCE' }],
      },
    ];
    expect(readText(output)).toBe('Conclusion.\n### SOURCE');
  });

  it('skips a trailing message that carries no text', () => {
    const output = [message('The answer.'), { type: 'message', content: [] }];
    expect(readText(output)).toBe('The answer.');
  });

  it('never reads prose out of a tool payload', () => {
    // The A2A outputs carry the contract text verbatim. Folding them in would put a raw corpus
    // dump on a wall screen.
    const output = [
      {
        type: 'a2a_preview_call_output',
        name: 'zava-media-contracts-a2a',
        content: [{ type: 'output_text', text: 'ARTICLE 6 — DELIVERY VARIANCE. The Agency shall…' }],
      },
      message('Contoso is entitled to a credit.'),
    ];
    expect(readText(output)).toBe('Contoso is entitled to a credit.');
  });

  it('returns nothing rather than something when there is no message', () => {
    expect(readText([{ type: 'mcp_list_tools', server_label: 'fabricdataagent' }])).toBe('');
    expect(readText(null)).toBe('');
  });
});

describe('reading which agents fired', () => {  it('does not credit Fabric for merely being listed', () => {
    const output = [
      { type: 'mcp_list_tools', server_label: 'fabricdataagent' },
      { type: 'a2a_preview_call', name: 'zava-media-contracts-a2a' },
      { type: 'a2a_preview_call_output', name: 'zava-media-contracts-a2a' },
      message('The contract says so.'),
    ];
    expect(collectTools(output)).toEqual(['zava-media-contracts-a2a']);
  });

  it('counts each hop once, however many times it appears', () => {
    const output = [
      { type: 'a2a_preview_call', name: 'DataAgent_Zava_Media_Analyst' },
      { type: 'a2a_preview_call_output', name: 'DataAgent_Zava_Media_Analyst' },
      { type: 'a2a_preview_call', name: 'zava-media-contracts-a2a' },
      { type: 'a2a_preview_call_output', name: 'zava-media-contracts-a2a' },
      { type: 'a2a_preview_call', name: 'zava-media-contracts-a2a' },
    ];
    expect(collectTools(output)).toEqual([
      'DataAgent_Zava_Media_Analyst',
      'zava-media-contracts-a2a',
    ]);
  });

  it('reports an unfamiliar name rather than hiding it', () => {
    // The rail shows provenance. An unrecognised true name is evidence; a friendly label
    // guessed for it would be a claim.
    const output = [{ type: 'function_call', name: 'some_new_subordinate' }];
    expect(collectTools(output)).toEqual(['some_new_subordinate']);
  });

  it('says nothing fired when nothing did', () => {
    // An empty list is a meaningful result — the supervisor answered from its own context —
    // and the rail is expected to show that rather than imply a source.
    expect(collectTools([message('An answer with no lookup.')])).toEqual([]);
  });
});

/**
 * The provenance line is the one the room reads, and the supervisor names its subordinates
 * with deployment identifiers. Unlabelled, the punchline of the demo renders as
 * "Read from DataAgent_Zava_Media_Analyst · zava-media-contracts-a2a · cross-referenced".
 */
describe('naming the sources on screen', () => {
  it('translates both subordinates the supervisor can call', () => {
    for (const name of ['DataAgent_Zava_Media_Analyst', 'zava-media-contracts-a2a']) {
      const label = SOURCE_LABEL[name];
      expect(label, `${name} would render as a deployment identifier`).toBeTruthy();
      expect(label).not.toMatch(/[_-]|a2a|DataAgent/);
    }
  });

  it('does not quietly file a subordinate as scaffolding', () => {
    // NOT_A_SOURCE removes steps before the "nothing was consulted" check. An agent listed
    // there would erase a real hop and turn a crossed answer into an ungrounded-looking one.
    expect(NOT_A_SOURCE.has('DataAgent_Zava_Media_Analyst')).toBe(false);
    expect(NOT_A_SOURCE.has('zava-media-contracts-a2a')).toBe(false);
  });
});
