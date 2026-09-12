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
import {
  ExpressCompiler,
  bindCommitContext,
  bindDerivedLabels,
  stripPanelActions,
} from '../src/index.js';
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

describe('bindDerivedLabels', () => {
  const picker = (nightsLabel?: unknown) => [
    {
      surfaceId: 's',
      components: [
        {
          id: 'dates',
          component: 'DateRangePicker',
          label: 'Dates',
          start: { path: '/trip/startDate' },
          end: { path: '/trip/endDate' },
          ...(nightsLabel === undefined ? {} : { nightsLabel }),
        },
      ],
    },
  ];

  const bind = (nightsLabel?: unknown) => {
    const [surface] = picker(nightsLabel);
    const messages: any[] = [{ version: 'v0.9.1', updateComponents: surface }];
    bindDerivedLabels(messages);
    return messages[0].updateComponents.components[0].nightsLabel;
  };

  const CALL = {
    call: 'formatString',
    args: { value: '${calcNights(start:${/trip/startDate}, end:${/trip/endDate})} nights' },
  };

  it('binds a picker that was given no label at all', () => {
    expect(bind()).toEqual(CALL);
  });

  /**
   * A template is the right answer already — the renderer resolves it — so
   * rewriting it would only discard wording the model chose.
   */
  it('leaves a template the model wrote', () => {
    const written = '${calcNights(start: ${/trip/startDate}, end: ${/trip/endDate})} nights away';
    expect(bind(written)).toBe(written);
  });

  /** Correct today, wrong the moment the traveler moves a date. */
  it('replaces a fixed count', () => {
    expect(bind('7 nights')).toEqual(CALL);
    expect(bind('1 night')).toEqual(CALL);
  });

  it('leaves a caption a function could not have written', () => {
    expect(bind('including the wedding night')).toBe('including the wedding night');
  });

  it('leaves a label the model already bound to a call', () => {
    const already = { call: 'calcNights', args: { start: { path: '/a' }, end: { path: '/b' } } };
    expect(bind(already)).toEqual(already);
  });

  it('leaves a picker holding literal dates, which has nothing to recompute', () => {
    const messages: any[] = [
      {
        version: 'v0.9.1',
        updateComponents: {
          surfaceId: 's',
          components: [
            { id: 'd', component: 'DateRangePicker', start: '2027-04-12', end: '2027-04-19' },
          ],
        },
      },
    ];
    bindDerivedLabels(messages);
    expect(messages[0].updateComponents.components[0].nightsLabel).toBeUndefined();
  });
});

describe('stripPanelActions', () => {
  const surface = (surfaceId: string) => ({
    version: 'v0.9.1',
    updateComponents: {
      surfaceId,
      components: [
        { id: 'label', component: 'Text', text: 'Iberia IB614' },
        { id: 'changeLabel', component: 'Text', text: 'Change' },
        {
          id: 'change',
          component: 'Button',
          child: 'changeLabel',
          action: { event: { name: 'change', context: { field: 'selectedFlight' } } },
        },
        { id: 'changeRow', component: 'Row', children: ['change'] },
        { id: 'root', component: 'Column', children: ['label', 'changeRow'] },
      ],
    },
  });

  const ids = (messages: any[]) =>
    messages[0].updateComponents.components.map((c: any) => c.id);

  it('leaves the panel alone — a change there is the one thing it may do', () => {
    const messages: any[] = [surface('sidebar')];
    stripPanelActions(messages, ['sidebar', 'home']);
    expect(ids(messages)).toContain('change');
  });

  /**
   * The live failure: the panel's record drawn a second time inside the card
   * the traveler was still filling in, so one decision had two Change buttons.
   */
  it('drops a change button drawn in the conversation', () => {
    const messages: any[] = [surface('inline-1')];
    stripPanelActions(messages, ['sidebar', 'home']);
    expect(ids(messages)).not.toContain('change');
  });

  it('drops the row that held nothing else, and unlinks it from the root', () => {
    const messages: any[] = [surface('inline-1')];
    stripPanelActions(messages, ['sidebar', 'home']);
    expect(ids(messages)).not.toContain('changeRow');
    const root = messages[0].updateComponents.components.find((c: any) => c.id === 'root');
    expect(root.children).toEqual(['label']);
  });

  it('keeps a commit button, which is not a change', () => {
    const messages: any[] = [
      {
        version: 'v0.9.1',
        updateComponents: {
          surfaceId: 'inline-1',
          components: [
            {
              id: 'go',
              component: 'Button',
              action: { event: { name: 'search_flights', context: {} } },
            },
            { id: 'root', component: 'Column', children: ['go'] },
          ],
        },
      },
    ];
    stripPanelActions(messages, ['sidebar', 'home']);
    expect(ids(messages)).toContain('go');
  });
});
