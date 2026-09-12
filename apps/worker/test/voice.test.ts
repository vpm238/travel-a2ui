/**
 * The voice relay's contract with the Live API.
 *
 * Two of the three bugs found building this were invisible rather than loud —
 * a socket that connected and then said nothing, and a `setup` the API would
 * have rejected — so these tests are about the shapes, not about audio.
 */

import { describe, expect, it } from 'vitest';

import { providerFor } from '../src/providers/index.js';

import { setupFrame, voiceTools, runVoiceTool, VOICE_MODEL } from '../src/voice.js';

describe('the tools a voice turn gets', () => {
  it('leads with the surface tools, because drawing is the job', () => {
    const names = voiceTools().map((tool) => tool.name);
    expect(names[0]).toMatch(/^show_/);
    expect(names).toContain('show_flight_options');
  });

  it('still carries the data tools, for a decision with nothing to draw', () => {
    expect(voiceTools().map((tool) => tool.name)).toContain('save_trip');
  });

  it('gives every declaration a description, which the API requires', () => {
    for (const tool of voiceTools()) expect(tool.description.length).toBeGreaterThan(10);
  });
});

describe('the setup frame', () => {
  const frame = () =>
    setupFrame({ model: VOICE_MODEL, systemInstruction: 'Be a travel agent.' }) as any;

  it('asks for audio out and both transcripts', () => {
    const setup = frame().setup;
    expect(setup.generationConfig.responseModalities).toEqual(['AUDIO']);
    // Without these the call has no readable record, and a caller cannot see
    // that they were heard correctly.
    expect(setup.inputAudioTranscription).toBeDefined();
    expect(setup.outputAudioTranscription).toBeDefined();
  });

  it('names the model the way the API wants it', () => {
    expect(frame().setup.model).toBe(`models/${VOICE_MODEL}`);
  });

  it('carries the travel role and the voice brief together', () => {
    const text = frame().setup.systemInstruction.parts[0].text;
    expect(text).toContain('Be a travel agent.');
    expect(text).toContain('Never read options aloud');
  });

  /**
   * The Live API rejects the whole `setup` — not the offending key — when a
   * declaration carries JSON Schema keywords outside the subset it accepts.
   * Our tool schemas are written for Gemini's function calling and do.
   */
  it('strips the schema keywords the Live API refuses', () => {
    const json = JSON.stringify(frame().setup.tools);
    expect(json).not.toContain('additionalProperties');
    expect(json).not.toContain('$schema');
    expect(json).not.toContain('"strict"');
  });

  it('keeps the parts of the schema that describe arguments', () => {
    const json = JSON.stringify(frame().setup.tools);
    expect(json).toContain('properties');
    expect(json).toContain('destination');
  });
});

describe('running a tool on a call', () => {
  const context = () => {
    const trip: Record<string, unknown> = {
      destination: 'Madrid',
      origin: 'JFK',
      startDate: '2027-04-12',
      endDate: '2027-04-19',
      travelers: 2,
    };
    return {
      trip,
      saveTrip: (patch: Record<string, unknown>) => Object.assign(trip, patch),
      provider: providerFor(undefined),
    };
  };

  it('draws a surface and hands the model only a summary', async () => {
    const outcome = await runVoiceTool('show_flight_options', { destination: 'Madrid' }, context());

    expect(outcome.ui?.messages.length).toBeGreaterThan(0);
    // The whole point: the flight list goes to the screen, not into the
    // model's context, where it would invite reading the list out loud.
    expect(JSON.stringify(outcome.response)).not.toContain('FlightOption');
    expect(outcome.response).toMatchObject({ shown: true });
  });

  it('reports a refusal as a result rather than throwing mid-call', async () => {
    const outcome = await runVoiceTool('show_flight_options', {}, { trip: {}, saveTrip: () => {}, provider: providerFor(undefined) });

    expect(outcome.ui).toBeUndefined();
    expect(outcome.response).toMatchObject({ shown: false });
  });

  it('routes a data tool the ordinary way, with no surface', async () => {
    const outcome = await runVoiceTool('save_trip', { travelers: 3 }, context());

    expect(outcome.ui).toBeUndefined();
    expect(JSON.stringify(outcome.response)).toContain('saved');
  });
});
