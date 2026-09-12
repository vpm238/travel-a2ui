/**
 * The interface, drawn before the data that fills it exists.
 *
 * A surface used to appear only once the model had finished writing it, which
 * meant the screen sat empty for as long as searching for flights takes and
 * then everything arrived at once. The interface should be the *first* thing
 * that happens, not the last: the moment the agent decides to look something
 * up, the shape of the answer is already known, so it can be on screen while
 * the looking-up happens and fill in as results land.
 *
 * Nothing new is needed to do that — it is three messages A2UI already has:
 *
 *     createSurface     the surface exists
 *     updateDataModel   seeded with blank rows, so bindings resolve to nothing
 *     updateComponents  the layout paints, every field pending
 *       … tool runs …
 *     updateDataModel   the rows arrive, and the cards fill in
 *
 * The components are sent **once**. Only the data model changes afterwards,
 * which is what makes this cheap: no recompile, no re-send of a tree, and the
 * card the traveller is looking at does not get replaced underneath them.
 *
 * A field that is pending and a field that is empty are told apart by the data
 * model itself — an unresolved path is pending, a path resolving to an empty
 * string is empty — so no flag has to be invented to say which. See `isPending`
 * in the renderer.
 *
 * The model still composes the real surface when it has the results, and that
 * replaces this one under the same id. This is the opening, not the answer.
 */

import type { A2uiMessage, ExpressCompiler, ProtocolVersion } from '@travel-a2ui/express';

/**
 * How many blank rows to lay out.
 *
 * Four, because that is what every provider returns after its own `slice(0, 4)`
 * — so the skeleton is the size of the thing arriving and the list does not
 * jump when it does. A provider that returns fewer leaves blank rows behind,
 * which is why `fill` replaces the whole array rather than patching row by row.
 */
const PENDING_ROWS = 4;

/** Rows that exist and hold nothing, so a `_template` repeats over them. */
const blankRows = (count: number): Record<string, never>[] =>
  Array.from({ length: count }, () => ({}));

interface Blueprint {
  /** Where the rows live in the data model. */
  path: string;
  /** Express for a surface whose every field is bound and none are filled. */
  express(surfaceId: string): string;
  /** The rows out of a tool result, or null when there is nothing to show. */
  rows(result: unknown): unknown[] | null;
}

function resultRows(result: unknown, key: string): unknown[] | null {
  if (!result || typeof result !== 'object') return null;
  const rows = (result as Record<string, unknown>)[key];
  return Array.isArray(rows) && rows.length > 0 ? rows : null;
}

/**
 * `cabin` is absent on purpose.
 *
 * It is a plain enum in the catalog rather than a bindable common type, so the
 * compiler refuses `cabin=$cabin` — correctly, and with a message that says so.
 * A static property cannot take part in a surface that is filled later, which
 * is a real constraint on what a skeleton can promise.
 */
const BLUEPRINTS: Record<string, Blueprint> = {
  search_flights: {
    path: '/flights',
    rows: (result) => resultRows(result, 'flights'),
    express: (surfaceId) =>
      [
        `surface(${JSON.stringify(surfaceId)})`,
        'head = Text("Finding flights", variant="h3")',
        'row = FlightOption($airline, $departTime, $arriveTime, $origin, $destination, $price, ' +
          'Event("select_flight", {id: $id, price: $price}), duration=$duration, stops=$stops, ' +
          'flightNumber=$flightNumber, badge=$badge)',
        'list = List(_template($/flights, row))',
        'root = Column([head, list])',
      ].join('\n'),
  },
  search_hotels: {
    path: '/hotels',
    rows: (result) => resultRows(result, 'hotels'),
    express: (surfaceId) =>
      [
        `surface(${JSON.stringify(surfaceId)})`,
        'head = Text("Finding places to stay", variant="h3")',
        'row = HotelCard($name, $price, Event("select_hotel", {id: $id, name: $name}), ' +
          'neighborhood=$neighborhood, rating=$rating, badge=$badge)',
        'list = List(_template($/hotels, row))',
        'root = Column([head, list])',
      ].join('\n'),
  },
};

export interface PendingSurface {
  /** Paints the layout with nothing in it. Sent before the tool runs. */
  opening: A2uiMessage[];
  /** Fills it from the tool's result, or null if there is nothing to fill. */
  fill(result: unknown): A2uiMessage[] | null;
}

/**
 * The surface a tool is about to fill, if it is one that fills a surface.
 *
 * Returns nothing for tools whose answer has no predictable shape — asking the
 * model what the trip costs does not tell you what it will draw — and a
 * skeleton for a shape nobody ends up filling is worse than no skeleton.
 */
export function pendingSurfaceFor(
  toolName: string,
  surfaceId: string,
  compiler: ExpressCompiler,
  catalogId: string,
  version: ProtocolVersion,
): PendingSurface | undefined {
  const blueprint = BLUEPRINTS[toolName];
  if (!blueprint) return undefined;

  let components: A2uiMessage[];
  try {
    components = compiler.compile(blueprint.express(surfaceId), {
      surfaceId,
      catalogId,
      version,
    });
  } catch {
    // A skeleton that will not compile is not worth failing a turn over: the
    // model's own surface still arrives, just without the head start.
    return undefined;
  }

  const seed: A2uiMessage = {
    version,
    updateDataModel: { surfaceId, path: blueprint.path, value: blankRows(PENDING_ROWS) },
  } as unknown as A2uiMessage;

  // `createSurface` first, then the blank rows, then the components — so the
  // layout never paints against a data model that does not exist yet.
  const created = components.filter((message) => 'createSurface' in message);
  const rest = components.filter((message) => !('createSurface' in message));

  return {
    opening: [...created, seed, ...rest],
    fill(result: unknown) {
      const rows = blueprint.rows(result);
      if (!rows) return null;
      return [
        {
          version,
          updateDataModel: { surfaceId, path: blueprint.path, value: rows },
        } as unknown as A2uiMessage,
      ];
    },
  };
}
