/**
 * A worked example for any component in the catalog, generated from its schema.
 *
 * The catalog page used to list signatures and prop tables, which tells you a
 * `FlightOption` takes nine arguments and nothing at all about what one looks
 * like. Showing the component itself is the answer, and the only honest way to
 * do that is to *render* it — same compiler, same components, same path a real
 * surface takes. A picture of a component is a thing that can be out of date; a
 * rendered one cannot.
 *
 * These are derived rather than written down, because a hand-maintained gallery
 * is a second catalog that drifts. Add a component to `build_catalog.py` and it
 * gets a preview on the next reload without anyone remembering to write one.
 *
 * Derivation only gets you so far, though. A generated `FlightOption` reading
 * "label, label, label, 2" is technically a preview and practically useless, so
 * `FLAVOUR` supplies real-looking values by property name — a departure time
 * that looks like a time, a fare that looks like a fare. That is a presentation
 * detail and not a second source of truth: nothing here says which components
 * exist or what arguments they take, only what to put in them.
 */

import { CatalogHelper } from './catalog.js';
import type { CatalogSchema, SchemaNode } from './types.js';

/**
 * Plausible values by property name, most specific first.
 *
 * Matched on the whole name, then on a suffix, so `nightlyPrice` and `price`
 * both read as money without either being listed twice.
 */
const FLAVOUR: Array<[RegExp, string | number | boolean]> = [
  [/^(airline|carrier)$/i, 'Iberia'],
  [/^flightNumber$/i, 'IB6250'],
  [/^(depart|departure|departTime)$/i, '18:40'],
  [/^(arrive|arrival|arriveTime)$/i, '08:15 +1'],
  [/^(origin|from)$/i, 'JFK'],
  [/^(destination|to)$/i, 'MAD'],
  [/^duration$/i, '7h 35m'],
  [/^stops$/i, 'Nonstop'],
  [/^badge$/i, 'Cheapest'],
  [/^(neighbourhood|neighborhood|area)$/i, 'La Latina'],
  [/^rating$/i, 4.5],
  [/^(reviews|reviewCount)$/i, 812],
  [/^nights$/i, 3],
  [/(price|fare|amount|total|budget|nightly)$/i, '$412'],
  [/^(value|current)$/i, 3],
  [/^max$/i, 10],
  [/^min$/i, 1],
  [/^(count|travelers|adults|quantity)$/i, 2],
  [/^(date|startDate|start)$/i, '2027-04-12'],
  [/^(endDate|end)$/i, '2027-04-19'],
  [/^(time)$/i, '10:00'],
  [/^(caption|summary|note|description|subtitle)$/i, 'Lands early enough for dinner'],
  [/^(label|title|text|heading|name|place|city)$/i, 'Madrid'],
  [/^(url|href|src|image)$/i, 'https://example.com/madrid.jpg'],
  [/^category$/i, 'sight'],
  [/^location$/i, 'Paseo del Prado 23'],
];

/** Hand-written examples where a derived one would not show the component off. */
const SPECIAL: Record<string, string> = {
  // A list is only interesting with something in it, and a template needs a
  // data model to repeat over — neither of which a per-property walk produces.
  List: `$/items/0/label = "Passport"
$/items/1/label = "Adapter"
row = Text($label)
root = List(_template($/items, row))`,

  Column: `a = Text("Outbound", variant="h4")
b = Text("JFK → MAD · Sun 12 Apr")
root = Column([a, b], align="stretch")`,

  Row: `a = Text("Total")
b = Text("$1,236")
root = Row([a, b], justify="spaceBetween")`,

  Card: `inner = Text("Anything can go in a card.")
root = Card(inner)`,

  ItineraryDay: `a1 = ActivityItem("Prado Museum", "10:00", category="sight", duration="2h")
a2 = ActivityItem("Lunch at Sobrino", "13:30", category="food", duration="1h 30m")
root = ItineraryDay("Day 2 — Old Madrid", [a1, a2], date="Mon 13 Apr", summary="Art, then a long lunch")`,

  PriceSummary: `root = PriceSummary([{label: "Flights", amount: "$824"}, {label: "Hotel · 6 nights", amount: "$1,746"}, {label: "Estimated meals", amount: "$540"}], total="$3,110", caption="2 travellers")`,

  ExpenseSplit: `root = ExpenseSplit("Dinner at Sobrino", "€96", [{name: "You"}, {name: "Sam"}])`,

  MapPreview: `root = MapPreview([{label: "Madrid"}, {label: "Toledo"}], caption="Day trip, 70km south")`,

  WeatherStrip: `root = WeatherStrip([{day: "Mon", high: 21, low: 11, condition: "sunny"}, {day: "Tue", high: 19, low: 10, condition: "cloudy"}], place="Madrid")`,

  TripCalendar: `root = TripCalendar("2027-04-12", "2027-04-18", marks=[{date: "2027-04-12", icon: "plane", label: "Fly out"}, {date: "2027-04-14", icon: "🎨", label: "Prado"}, {date: "2027-04-18", icon: "plane", label: "Fly home"}], title="Madrid", caption="6 nights")`,

  ChoicePicker: `root = ChoicePicker("Cabin", "mutuallyExclusive", [{label: "Economy", value: "economy"}, {label: "Premium", value: "premium"}], $/cabin)`,

  // The rest are here because the derived version is legal and absurd —
  // `CheckBox("Madrid", 3)` compiles, draws, and teaches nothing. A property
  // walk can pick a value of the right *type*; only a person can pick one that
  // reads like a trip. These are what the catalog reference shows, so they are
  // worth the lines.
  CheckBox: `root = CheckBox("I need somewhere to stay in Chicago", $/stops/1/needsStay)`,

  ActivityItem: `root = ActivityItem("Prado Museum", "10:00", category="sight", location="Paseo del Prado 23", duration="2h", note="Book the timed entry")`,

  TextField: `root = TextField("Flying from", $/trip/origin, validationRegexp="^[A-Za-z]{3}$")`,

  Slider: `root = Slider("Budget, all in", 500, 6000, $/trip/budget)`,

  TravelerCounter: `root = TravelerCounter("Travelers", $/trip/travelers, min=1, max=9, caption="Adults on this leg")`,

  DateRangePicker: `root = DateRangePicker("Trip dates", $/trip/startDate, $/trip/endDate, nightsLabel=formatString("\${calcNights(start: \${/trip/startDate}, end: \${/trip/endDate})} nights"))`,

  StatTile: `root = StatTile("Nights in Madrid", "7", caption="12–19 April", tone="accent")`,

  ProgressMeter: `root = ProgressMeter("Spent of budget", 1840, 3000, caption="$1,160 left")`,

  Text: `root = Text("Madrid · 2 travellers · 12–19 April", variant="h3")`,

  HotelCard: `root = HotelCard("Hotel Único Madrid", "$291 / night", Event("select_hotel", {id: "unico"}), neighborhood="Salamanca", rating="9.1 · Superb", amenities=["Breakfast", "Rooftop", "Free cancellation"], badge="Best located")`,

  FlightOption: `root = FlightOption("Iberia", "18:40", "08:15 +1", "JFK", "MAD", "$412", Event("select_flight", {id: "IB6252"}), duration="7h 35m", stops="Nonstop", flightNumber="IB6252", cabin="economy", badge="Cheapest")`,
};

const quote = (value: string): string => `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;

/** A literal for one property, from its name and its schema. */
function valueFor(property: string, schema: SchemaNode | undefined, enumValues?: string[]): string {
  if (enumValues?.length) return quote(enumValues[0]!);

  for (const [pattern, value] of FLAVOUR) {
    if (!pattern.test(property)) continue;
    return typeof value === 'string' ? quote(value) : String(value);
  }

  // Nothing recognised the name, so fall back to the declared type.
  const type = schema?.['type'];
  if (type === 'number' || type === 'integer') return '1';
  if (type === 'boolean') return 'true';
  if (type === 'array') return '[]';
  return quote(property);
}

/**
 * Express that draws one component, ready to compile.
 *
 * Required properties only, plus any optional one this catalog gives an enum —
 * a variant or a tone is usually the point of the component, and the default is
 * rarely the interesting case. Returns null for a component the catalog does
 * not have.
 */
export function exampleExpress(catalog: CatalogSchema, name: string): string | null {
  if (SPECIAL[name]) return SPECIAL[name]!;

  const helper = new CatalogHelper(catalog);
  if (!helper.hasComponent(name)) return null;

  const required = new Set(helper.getComponentRequired(name));
  const parts: string[] = [];
  const lines: string[] = [];

  // Positional arguments are matched by *position*, so the moment one is
  // skipped everything after it has to be named — otherwise a later required
  // argument silently lands in the slot of the optional one that was left out.
  // Button is where this showed up: an optional `variant` between a required
  // child and a required action, and the action arrived as the variant.
  let named = false;

  for (const property of helper.getComponentProperties(name)) {
    const schema = helper.getPropertySchema(name, property);
    const enumValues = helper.getPropertyEnum(name, property);
    const isRequired = required.has(property);
    if (!isRequired && !enumValues) {
      // Skipped — so nothing after this may be positional.
      named = true;
      continue;
    }

    // A child slot takes a component id, so the child has to exist first.
    const ref = typeof schema?.['$ref'] === 'string' ? schema['$ref'] : '';
    const emit = (literal: string): void => {
      const positional = isRequired && !named;
      if (!positional) named = true;
      parts.push(positional ? literal : `${property}=${literal}`);
    };

    if (ref.includes('ComponentId') || ref.includes('ChildList')) {
      const childId = `${name.toLowerCase()}Child`;
      lines.push(`${childId} = Text("Inside ${name}")`);
      emit(ref.includes('ChildList') ? `[${childId}]` : childId);
      continue;
    }

    if (property === 'action') {
      emit(`Event("example", {component: ${quote(name)}})`);
      continue;
    }

    emit(valueFor(property, schema, enumValues ?? undefined));
  }

  lines.push(`root = ${name}(${parts.join(', ')})`);
  return lines.join('\n');
}
