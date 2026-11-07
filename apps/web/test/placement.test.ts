/**
 * Where a card sits in the conversation.
 *
 * A card belongs to the turn that first showed it. A later turn that sends it
 * data (a press marks the chosen flight) updates it in place; it must not draw
 * the same card again under the later turn.
 */

import { describe, expect, it } from 'vitest';

import { placeSurface, type Turn } from '../src/conversation.js';

const turn = (id: string, surfaces: string[] = []): Turn => ({
  id,
  role: 'assistant',
  text: '',
  parts: surfaces.map((surfaceId) => ({ kind: 'surface', surfaceId })),
  tools: [],
  streaming: false,
});

const shown = (turns: Turn[]) =>
  turns.map((t) => t.parts.flatMap((part) => (part.kind === 'surface' ? [part.surfaceId] : [])));

describe('placing a surface in the conversation', () => {
  it('puts a new card under the turn that drew it', () => {
    expect(shown(placeSurface([turn('a'), turn('b')], 'b', 'inline-2'))).toEqual([[], ['inline-2']]);
  });

  it('leaves an earlier card where it is when a later turn updates it', () => {
    const turns = [turn('a', ['inline-1']), turn('b')];
    expect(shown(placeSurface(turns, 'b', 'inline-1'))).toEqual([['inline-1'], []]);
  });

  it('never files the panel or home in the conversation', () => {
    expect(shown(placeSurface([turn('a')], 'a', 'sidebar'))).toEqual([[]]);
    expect(shown(placeSurface([turn('a')], 'a', 'home'))).toEqual([[]]);
  });

  it('records a card once within its own turn', () => {
    const turns = placeSurface(placeSurface([turn('a')], 'a', 'inline-1'), 'a', 'inline-1');
    expect(shown(turns)).toEqual([['inline-1']]);
  });
});
