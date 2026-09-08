/**
 * The server-side pass that guarantees a commit button carries the answer.
 *
 * These are the cases that decide whether a traveler's edit survives the trip
 * back to the agent, so they are written against compiled A2UI rather than
 * Express: the guarantee has to hold for whatever the model produced.
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { ExpressCompiler, bindCommitContext } from '../src/index.js';
import type { A2uiMessage, ComponentNode, JsonObject } from '../src/types.js';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const catalog = JSON.parse(
  readFileSync(join(root, 'catalogs', 'a2ui-travel', 'catalog.json'), 'utf8'),
);
const compiler = new ExpressCompiler(catalog, 'v0.9.1');

function compile(source: string): A2uiMessage[] {
  return compiler.compile(source, { surfaceId: 's', catalogId: catalog.catalogId, version: 'v0.9.1' });
}

/** The context map on the first event action, or on the one named `eventName`. */
function contextOf(messages: A2uiMessage[], eventName?: string): JsonObject {
  for (const message of messages) {
    const components: ComponentNode[] =
      ('createSurface' in message && message.createSurface.components) ||
      ('updateComponents' in message && message.updateComponents.components) ||
      [];
    for (const node of components) {
      const action = node['action'] as JsonObject | undefined;
      const event = action?.['event'] as JsonObject | undefined;
      if (!event) continue;
      if (eventName && event['name'] !== eventName) continue;
      return (event['context'] as JsonObject) ?? {};
    }
  }
  return {};
}

const paths = (context: JsonObject) =>
  Object.values(context)
    .map((v) => (v as JsonObject)?.['path'])
    .filter(Boolean)
    .sort();

describe('commit context', () => {
  it('carries every edited path, even when the model bound none', () => {
    const messages = compile(`
      root = Column([
        TextField("From", value=$/trip/origin),
        DateRangePicker("Dates", start=$/trip/startDate, end=$/trip/endDate),
        TravelerCounter("Travelers", value=$/trip/travelers),
        Button("Search", action=Event("search_flights"))
      ])
    `);

    const context = contextOf(bindCommitContext(messages));
    expect(paths(context)).toEqual([
      '/trip/endDate',
      '/trip/origin',
      '/trip/startDate',
      '/trip/travelers',
    ]);
  });

  it('keeps the keys the model chose and adds only what is missing', () => {
    const messages = compile(`
      root = Column([
        TextField("From", value=$/trip/origin),
        TextField("To", value=$/trip/destination),
        Button("Go", action=Event("go", {departsFrom: $/trip/origin}))
      ])
    `);

    const context = contextOf(bindCommitContext(messages));
    // The model's own name for the path it bound survives.
    expect((context['departsFrom'] as JsonObject)['path']).toBe('/trip/origin');
    expect(paths(context)).toEqual(['/trip/destination', '/trip/origin']);
    // ...and it was not bound a second time under a generated key.
    expect(Object.keys(context)).toHaveLength(2);
  });

  it('leaves a surface with nothing to edit alone', () => {
    const messages = compile(`
      root = Column([
        Text("Madrid in April"),
        Button("Book it", action=Event("book"))
      ])
    `);
    expect(contextOf(bindCommitContext(messages))).toEqual({});
  });

  it('fills every button, not just the first', () => {
    const messages = compile(`
      root = Column([
        Slider("Budget", value=$/trip/budget),
        Button("Apply", action=Event("apply")),
        Button("Start over", action=Event("reset"))
      ])
    `);
    const bound = bindCommitContext(messages);
    expect(paths(contextOf(bound, 'apply'))).toEqual(['/trip/budget']);
    expect(paths(contextOf(bound, 'reset'))).toEqual(['/trip/budget']);
  });

  it('does not mistake a child-list template for an edited value', () => {
    const messages = compile(`
      row = Text($item/name)
      root = Column([
        List(_template($/flights, row)),
        Button("Pick", action=Event("pick"))
      ])
    `);
    expect(contextOf(bindCommitContext(messages))).toEqual({});
  });

  it('disambiguates two paths ending in the same word', () => {
    const messages = compile(`
      root = Column([
        TextField("Trip from", value=$/trip/origin),
        TextField("Leg from", value=$/leg/origin),
        Button("Go", action=Event("go"))
      ])
    `);
    const context = contextOf(bindCommitContext(messages));
    expect(paths(context)).toEqual(['/leg/origin', '/trip/origin']);
    expect(Object.keys(context)).toHaveLength(2);
  });

  it('binds a button created in a later message than the field', () => {
    const first = compile(`
      root = Column([TextField("From", value=$/trip/origin)])
    `);
    const later: A2uiMessage[] = [
      {
        version: 'v0.9.1',
        updateComponents: {
          surfaceId: 's',
          components: [
            {
              id: 'send',
              component: 'Button',
              label: 'Go',
              action: { event: { name: 'go' } },
            } as ComponentNode,
          ],
        },
      },
    ];
    const bound = bindCommitContext([...first, ...later]);
    expect(paths(contextOf(bound, 'go'))).toEqual(['/trip/origin']);
  });
});

describe('a surface with no way to send', () => {
  it('gets a button, because editors with nothing to press is a dead end', () => {
    const messages = compile(`
      from = TextField("From", value=$/trip/origin)
      when = DateRangePicker("Dates", start=$/trip/startDate, end=$/trip/endDate)
      root = Column([from, when])
    `);

    const bound = bindCommitContext(messages);
    const context = contextOf(bound, 'commit_surface');
    expect(paths(context)).toEqual(['/trip/endDate', '/trip/origin', '/trip/startDate']);
  });

  it('puts it inside the layout, not floating unattached', () => {
    const messages = compile(`
      from = TextField("From", value=$/trip/origin)
      root = Column([from])
    `);
    const bound = bindCommitContext(messages);
    const components = bound.flatMap((message: A2uiMessage) =>
      'updateComponents' in message ? message.updateComponents.components : [],
    );
    const root = components.find((node) => node.id === 'root')!;
    const added = components.find((node) => node.component === 'Button')!;
    expect(root['children']).toContain(added.id);
  });

  it('adds nothing when the model already drew a button', () => {
    const messages = compile(`
      from = TextField("From", value=$/trip/origin)
      go = Button("Search", action=Event("search"))
      root = Column([from, go])
    `);
    const bound = bindCommitContext(messages);
    const buttons = bound
      .flatMap((message: A2uiMessage) =>
        'updateComponents' in message ? message.updateComponents.components : [],
      )
      .filter((node) => node.component === 'Button');
    expect(buttons).toHaveLength(1);
    expect(paths(contextOf(bound, 'search'))).toEqual(['/trip/origin']);
  });

  it('adds nothing to a surface that only displays', () => {
    const messages = compile(`
      title = Text("Madrid in April")
      root = Column([title])
    `);
    const bound = bindCommitContext(messages);
    const buttons = bound
      .flatMap((message: A2uiMessage) =>
        'updateComponents' in message ? message.updateComponents.components : [],
      )
      .filter((node) => node.component === 'Button');
    expect(buttons).toHaveLength(0);
  });
});
