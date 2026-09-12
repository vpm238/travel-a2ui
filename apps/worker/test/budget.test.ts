/**
 * Where a turn's input tokens actually go.
 *
 * Not a correctness test — a scale, printed so a pruning decision is made
 * against measured bytes rather than against which part *feels* big. Every
 * number here is characters of the request body, which is what gets tokenised.
 */

import { describe, it } from 'vitest';

import { buildSystemPrompt } from '../src/skills.js';
import { geminiTools } from '../src/tools.js';
import { CATALOG_ID } from '../src/agent.js';

describe('the per-turn budget', () => {
  it('reports what the model is sent', () => {
    const system = buildSystemPrompt({
      variant: 'express-monolithic',
      surface: 'inline',
      surfaceId: 'inline-1',
      catalogId: CATALOG_ID,
      trip: {},
      today: '2026-09-12',
    });
    const tools = JSON.stringify(geminiTools());

    const rows: Array<[string, number]> = [
      ['system instruction', system.length],
      ['  of which the skill', system.indexOf('## Grammar Rules') === -1 ? 0 : 0],
      ['tool schemas', tools.length],
    ];
    const total = system.length + tools.length;

    console.log('\n  per turn, in characters');
    for (const [what, n] of rows) {
      if (n === 0) continue;
      console.log(`  ${String(n).padStart(7)}  ${what}  (${Math.round((n / total) * 100)}%)`);
    }
    console.log(`  ${String(total).padStart(7)}  total\n`);

    console.log('  per tool schema');
    for (const tool of geminiTools()) {
      console.log(`  ${String(JSON.stringify(tool).length).padStart(7)}  ${tool.name}`);
    }
    console.log();
  });
});
