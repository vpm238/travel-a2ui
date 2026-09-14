---
name: a2ui-travel
description: UI component catalog signatures for a2ui-travel. Use when building a2ui-travel
  user interface components.
metadata:
  protocol_version: 0.9.1
  inference_format: express
  catalogs:
  - a2ui-travel
  catalog_id: https://travel-a2ui.dev/catalogs/a2ui-travel/catalog.json
---

## Positional Component Signatures

Use these exact positional signatures to instantiate components. Do not output property keys:
• ActivityItem(title, time?, category? (static), location?, duration?, note?, action? (static), done?, onRemove? (static))
  - Description: A single scheduled thing inside an ItineraryDay — a meal, a museum, a transfer, a check-in.
  - title: What it is, e.g. 'Prado Museum'.
  - time: Start time as a display string, e.g. '10:00'.
  - category: Drives the icon and colour the host uses. Must be one of: 'food', 'sight', 'transit', 'stay', 'outdoors', 'shopping', 'event', 'free'
  - location: Where it happens, e.g. 'Paseo del Prado 23'.
  - duration: How long to budget, e.g. '2h'.
  - note: One short practical note, e.g. 'Book the timed entry'.
  - action: Fired when the traveler taps the activity.
  - done: Whether the traveler has ticked this off.
  - onRemove: Fired when the traveler drops this activity. Give every activity one: a day plan is theirs to edit.
• Button(child (component ID), variant? (static), action (static), checks? (static))
  - child: The ID of the child component. Use a 'Text' component for a labeled button. Only use an 'Icon' if the requirements explicitly ask for an icon-only button.
  - variant: A hint for the button style. If omitted, a default button style is used. 'primary' indicates this is the main call-to-action button. 'borderless' means the button has no visual border or background, making its child content appear like a clickable link. Must be one of: 'default', 'primary', 'borderless'
• CheckBox(label, value, checks? (static))
  - label: The text to display next to the checkbox.
  - value: The current state of the checkbox (true for checked, false for unchecked).
• ChoicePicker(label?, variant? (static), options (static), value, displayStyle? (static), filterable? (static), checks? (static))
  - Description: A component that allows selecting one or more options from a list.
  - label: The label for the group of options.
  - variant: A hint for how the choice picker should be displayed and behave. Must be one of: 'multipleSelection', 'mutuallyExclusive'
  - options: The list of available options to choose from.
    List of maps keys:
    * label - The text to display for this option.
    * value - The stable value associated with this option.
  - value: The list of currently selected values. This should be bound to a string array in the data model.
  - displayStyle: The display style of the component. Must be one of: 'checkbox', 'chips'
  - filterable: If true, displays a search input to filter the options.
• Column(children, justify? (static), align? (static))
  - Description: A layout component that arranges its children vertically. To create a grid layout, nest Rows within this Column.
  - children: Defines the children. Use an array of strings for a fixed set of children, or a template object to generate children from a data list. Children cannot be defined inline, they must be referred to by ID.
  - justify: Defines the arrangement of children along the main axis (vertically). Use 'spaceBetween' to push items to the edges (e.g. header at top, footer at bottom), or 'start'/'end'/'center' to pack them together. Must be one of: 'start', 'center', 'end', 'spaceBetween', 'spaceAround', 'spaceEvenly', 'stretch'
  - align: Defines the alignment of children along the cross axis (horizontally). This is similar to the CSS 'align-items' property. Must be one of: 'center', 'end', 'start', 'stretch'
• DateRangePicker(label, start, end, action? (static), nightsLabel?, checks? (static))
  - Description: Picks the trip's start and end dates. Both bound values are RFC 3339 timestamps with an offset, e.g. '2026-04-12T00:00:00Z'.
  - label: What the range is for, e.g. 'When are you going?'.
  - start: Bound path for the start date (RFC 3339).
  - end: Bound path for the end date (RFC 3339).
  - action: Fired when the traveler commits a new range.
  - nightsLabel: Derived caption, e.g. '6 nights'.
• ExpenseSplit(title, total, participants (static), action? (static), actionLabel?)
  - Description: Splits a shared trip cost between travelers and shows who owes what.
  - title: What was paid for, e.g. 'Dinner at Sobrino'.
  - total: Preformatted total, e.g. '€96'.
  - participants: Who is splitting it. Static values only.
    List of maps keys:
    * name - Traveler's name.
    * share - Their share, preformatted, e.g. '€32'.
    * status - One of 'paid', 'owes', 'settled'.
  - action: Fired when the traveler settles or edits the split.
  - actionLabel: Label for that action, e.g. 'Settle up'.
• FlightOption(airline, departTime, arriveTime, origin, destination, price, action (static), duration?, stops?, flightNumber?, cabin? (static), selected?, badge?, total?)
  - Description: A single selectable flight itinerary leg. Use one per option when presenting a choice of flights; do not build flight rows by hand out of Row and Text.
  - airline: Operating carrier, e.g. 'Iberia' or 'Delta'.
  - departTime: Local departure time as a display string, e.g. '07:15'.
  - arriveTime: Local arrival time as a display string. Append '+1' when the flight lands on the next day, e.g. '19:40 +1'.
  - origin: Origin airport code, e.g. 'JFK'.
  - destination: Destination airport code, e.g. 'MAD'.
  - price: Preformatted price including currency, e.g. '$412'.
  - action: Fired when the traveler selects this flight. Required — an unselectable option is not an interface.
  - duration: Total travel time as a display string, e.g. '7h 25m'.
  - stops: Stop summary, e.g. 'Nonstop' or '1 stop · LIS'.
  - flightNumber: Marketing flight number, e.g. 'IB6250'.
  - cabin: Cabin the price refers to. Must be one of: 'economy', 'premium', 'business', 'first'
  - selected: Whether this option is currently chosen. Bind it to the data model so the selection survives a re-render.
  - badge: Short editorial tag, e.g. 'Cheapest' or 'Fastest'.
  - total: What this flight costs for everyone on this leg, when that is more than one person — preformatted, e.g. '$522 for 2'. Give it whenever the leg carries a party, and `price` is then read as the per-traveler fare.
• HotelCard(name, price, action (static), imageUrl?, neighborhood?, rating?, amenities? (static), selected?, badge?)
  - Description: A place to stay, presented as a rich card with imagery, rating and nightly price.
  - name: Property name.
  - price: Preformatted nightly or total price, e.g. '$186 / night'.
  - action: Fired when the traveler picks or opens this property.
  - imageUrl: Hero image URL. Omit for a generated placeholder.
  - neighborhood: Where it is, in words a traveler uses, e.g. 'Malasaña'.
  - rating: Rating as a display string, e.g. '4.6 (1,204)'.
  - amenities: Short amenity labels, at most five. Static values only.
  - selected: Whether this property is currently chosen.
  - badge: Short editorial tag, e.g. 'Walkable' or 'Best value'.
• ItineraryDay(title, children, date?, summary?, action? (static), onAdd? (static))
  - Description: One day of a trip. Its children are the day's ActivityItem components, in chronological order.
  - title: Day heading, e.g. 'Day 3 — Toledo'.
  - children: The day's activities, earliest first.
  - date: Date as a display string, e.g. 'Tue 14 Apr'.
  - summary: One-line character of the day, e.g. 'Old town, slow pace'.
  - action: Fired when the traveler opens or edits the whole day.
  - onAdd: Fired when the traveler wants something else in this day.
• List(children, direction? (static), align? (static))
  - children: Defines the children. Use an array of strings for a fixed set of children, or a template object to generate children from a data list.
  - direction: The direction in which the list items are laid out. Must be one of: 'vertical', 'horizontal'
  - align: Defines the alignment of children along the cross axis. Must be one of: 'start', 'center', 'end', 'stretch'
• MapPreview(markers (static), caption?, action? (static))
  - Description: A lightweight schematic map of the places in play. Not a live map — it orients the traveler and is safe to render offline.
  - markers: Places to pin. Static values only — the host lays them out relative to each other.
    List of maps keys:
    * label - Short place name shown next to the pin.
    * kind - One of 'stay', 'sight', 'food', 'transit'.
    * day - Optional day number this marker belongs to.
  - caption: One line describing what the map shows.
  - action: Fired when the traveler taps the map.
• PriceSummary(lines (static), total, totalLabel?, action? (static), actionLabel?, caption?)
  - Description: The money view: an itemized breakdown and a total. Use this instead of a hand-built table whenever you show what a trip costs.
  - lines: Itemized cost lines in display order. Static values only.
    List of maps keys:
    * label - What the line is for, e.g. 'Flights (2 travelers)'.
    * amount - Preformatted amount, e.g. '$824'.
    * note - Optional qualifier, e.g. 'refundable'.
  - total: Preformatted grand total, e.g. '$2,140'.
  - totalLabel: What the total is called, e.g. 'Trip total'.
  - action: Primary money action, e.g. hold or book.
  - actionLabel: Label for that action, e.g. 'Hold for 24h'.
  - caption: Fine print, e.g. 'Estimated, taxes included'.
• ProgressMeter(label, value, max, caption?, tone? (static))
  - Description: How far along something is — budget spent, packing done, bookings confirmed. `value` and `max` are numbers, not display strings.
  - label: What is progressing.
  - value: Current amount.
  - max: Amount that counts as complete.
  - caption: Reading in words, e.g. '$1,320 of $2,000'.
  - tone: Colour role for the bar. Must be one of: 'neutral', 'positive', 'caution', 'critical', 'accent'
• Row(children, justify? (static), align? (static))
  - Description: A layout component that arranges its children horizontally. To create a grid layout, nest Columns within this Row.
  - children: Defines the children. Use an array of strings for a fixed set of children, or a template object to generate children from a data list. Children cannot be defined inline, they must be referred to by ID.
  - justify: Defines the arrangement of children along the main axis (horizontally). Use 'spaceBetween' to push items to the edges, or 'start'/'end'/'center' to pack them together. Must be one of: 'center', 'end', 'spaceAround', 'spaceBetween', 'spaceEvenly', 'start', 'stretch'
  - align: Defines the alignment of children along the cross axis (vertically). This is similar to the CSS 'align-items' property, but uses camelCase values (e.g., 'start'). Must be one of: 'start', 'center', 'end', 'stretch'
• Slider(label?, min? (static), max (static), value, checks? (static))
  - label: The label for the slider.
  - min: The minimum value of the slider.
  - max: The maximum value of the slider.
  - value: The current value of the slider.
• StatTile(label, value, caption?, tone? (static), action? (static))
  - Description: One number that matters, sized for a dashboard grid. Home-surface staple: days until departure, budget left, bookings confirmed.
  - label: What the number measures.
  - value: The number as a display string, e.g. '17'.
  - caption: Context under the number, e.g. 'until Madrid'.
  - tone: Colour role for the tile. Must be one of: 'neutral', 'positive', 'caution', 'critical', 'accent'
  - action: Fired when the traveler taps the tile.
• Text(text, variant? (static))
  - text: The text content to display. While simple Markdown formatting is supported (i.e. without HTML, images, or links), utilizing dedicated UI components is generally preferred for a richer and more structured presentation.
  - variant: A hint for the base text style. Must be one of: 'h1', 'h2', 'h3', 'h4', 'h5', 'caption', 'body'
• TextField(label, value?, variant? (static), validationRegexp? (static), checks? (static))
  - label: The text label for the input field.
  - value: The value of the text field.
  - variant: The type of input field to display. Must be one of: 'longText', 'number', 'shortText', 'obscured'
  - validationRegexp: A regular expression used for client-side validation of the input.
• TravelerCounter(label, value, min? (static), max? (static), caption?, checks? (static))
  - Description: A stepper for party size. Bind `value` so the count survives a re-render and later turns can read it.
  - label: What is being counted, e.g. 'Adults'.
  - value: Bound path holding the current count.
  - min: Lowest allowed count.
  - max: Highest allowed count.
  - caption: Qualifier, e.g. 'Age 12+'.
• WeatherStrip(days (static), place?, caption?)
  - Description: A short forecast row for the destination. Purely informational.
  - days: Forecast entries in date order, at most seven. Static values only.
    List of maps keys:
    * day - Short day label, e.g. 'Tue'.
    * high - High temperature as a display string, e.g. '21°'.
    * low - Low temperature as a display string.
    * condition - One of 'sun', 'cloud', 'rain', 'storm', 'snow', 'fog'.
  - place: Where the forecast is for.
  - caption: One line of interpretation, e.g. 'Pack a light jacket'.

## Positional Function Signatures

Use these exact positional signatures to instantiate check rules or logic functions:
• calcNights(start, end)
  - Description: Returns the number of nights between two ISO-8601 dates (yyyy-MM-dd), counting the nights slept rather than the days spanned: a 12th-to-15th stay is 3. Returns 0 when either date is missing or the range is inverted, so a half-filled form shows a zero rather than nonsense.
  - start: The check-in date, as yyyy-MM-dd.
  - end: The check-out date, as yyyy-MM-dd.
• formatCurrency(value, currency, decimals?, grouping?)
  - Description: Formats a number as a currency string.
  - value: The monetary amount.
  - currency: The ISO 4217 currency code (e.g., 'USD', 'EUR').
  - decimals: Optional. The number of decimal places to show. Defaults to 0 or 2 depending on locale.
  - grouping: Optional. If true, uses locale-specific grouping separators (e.g. '1,000'). If false, returns raw digits (e.g. '1000'). Defaults to true.
• formatDate(value, format)
  - Description: Formats a timestamp into a string using a pattern.
  - value: The date to format.
  - format: A Unicode TR35 date pattern string.

Token Reference:
- Year: 'yy' (26), 'yyyy' (2026)
- Month: 'M' (1), 'MM' (01), 'MMM' (Jan), 'MMMM' (January)
- Day: 'd' (1), 'dd' (01), 'E' (Tue), 'EEEE' (Tuesday)
- Hour (12h): 'h' (1-12), 'hh' (01-12) - requires 'a' for AM/PM
- Hour (24h): 'H' (0-23), 'HH' (00-23) - Military Time
- Minute: 'mm' (00-59)
- Second: 'ss' (00-59)
- Period: 'a' (AM/PM)

Examples:
- 'MMM dd, yyyy' -> 'Jan 16, 2026'
- 'HH:mm' -> '14:30' (Military)
- 'h:mm a' -> '2:30 PM'
- 'EEEE, d MMMM' -> 'Friday, 16 January'
• formatNumber(value, decimals?, grouping?)
  - Description: Formats a number with the specified grouping and decimal precision.
  - value: The number to format.
  - decimals: Optional. The number of decimal places to show. Defaults to 0 or 2 depending on locale.
  - grouping: Optional. If true, uses locale-specific grouping separators (e.g. '1,000'). If false, returns raw digits (e.g. '1000'). Defaults to true.
• formatString(value)
  - Description: Performs string interpolation of data model values and other functions in the catalog functions list and returns the resulting string. The value string can contain interpolated expressions in the `${expression}` format. Supported expression types include: JSON Pointer paths to the data model (e.g., `${/absolute/path}` or `${relative/path}`), and client-side function calls (e.g., `${now()}`). Function arguments must be named (e.g., `${formatDate(value:${/currentDate}, format:'MM-dd')}`). To include a literal `${` sequence, escape it as `\${`.
• openUrl(url)
  - Description: Opens the specified URL in a browser or handler. This function has no return value.
  - url: The URL to open.
• pluralize(value, zero?, one?, two?, few?, many?, other)
  - Description: Returns a localized string based on the Common Locale Data Repository (CLDR) plural category of the count (zero, one, two, few, many, other). Requires an 'other' fallback. For English, just use 'one' and 'other'.
  - value: The numeric value used to determine the plural category.
  - zero: String for the 'zero' category (e.g., 0 items).
  - one: String for the 'one' category (e.g., 1 item).
  - two: String for the 'two' category (used in Arabic, Welsh, etc.).
  - few: String for the 'few' category (e.g., small groups in Slavic languages).
  - many: String for the 'many' category (e.g., large groups in various languages).
  - other: The default/fallback string (used for general plural cases).

## Catalog Instructions

You are composing travel UI. A few house rules that matter more than anything else:

- Prefer a travel component over hand-assembling one out of Row/Column/Text. If
  you are showing a flight, use FlightOption. If you are showing a night's stay,
  use HotelCard. The host styles these natively and they carry semantics the
  plain layout primitives do not.
- Every option the user could plausibly act on needs an `action`. A flight the
  user cannot select is a screenshot, not an interface.
- Money is always a preformatted display string ("$412", "€1,180 total"). Do not
  emit bare numbers and hope the host formats them.
- Times are display strings in the traveler's local time ("07:15", "Tue 14 Apr").
  The one exception is DateRangePicker, whose bound values are RFC 3339.
- When you present a set of options, bind the user's current choice into the data
  model so a later turn can read it back — e.g. `$/trip/selectedOutbound`.
- Keep a surface to one job. An inline card answers the message it is attached
  to; the sidebar refines the trip in flight; the home surface summarizes.

### Examples:

---BEGIN 10-inline-flight-options---
# Inline: answering "find me a flight to Madrid" inside the chat feed.
# One surface, one job — three options and a way to pick one.
surface("inline-flights")
$/trip/selectedOutbound = ""
heading = Text("Outbound · JFK → MAD · Sun 12 Apr", variant="h3")
f1 = FlightOption("Iberia", "18:40", "08:15 +1", "JFK", "MAD", "$412", Event("select_flight", {id: "IB6250", price: "$412"}), duration="7h 35m", stops="Nonstop", flightNumber="IB6250", selected=$/trip/selectedOutbound, badge="Cheapest")
f2 = FlightOption("Delta", "21:10", "10:50 +1", "JFK", "MAD", "$468", Event("select_flight", {id: "DL126", price: "$468"}), duration="7h 40m", stops="Nonstop", flightNumber="DL126")
f3 = FlightOption("TAP", "17:25", "11:05 +1", "JFK", "MAD", "$367", Event("select_flight", {id: "TP208", price: "$367"}), duration="11h 40m", stops="1 stop · LIS", flightNumber="TP208", badge="Lowest fare")
note = Text("Prices are per traveler, round trip.")
root = Column([heading, f1, f2, f3, note])

---END 10-inline-flight-options---

---BEGIN 20-sidebar-refine---
# Sidebar: controls that refine the trip currently in focus.
# The sidebar is a persistent surface — target it by id and it replaces itself.
surface("sidebar")
$/filters/maxPrice = 600
$/filters/adults = 2
title = Text("Refine", variant="h3")
dates = DateRangePicker("Travel dates", $/filters/start, $/filters/end, action=Event("dates_changed"), nightsLabel="6 nights")
who = TravelerCounter("Adults", $/filters/adults, min=1, max=8)
budget = Slider("Max fare", 150, 1500, $/filters/maxPrice)
stops = ChoicePicker("Stops", "mutuallyExclusive", [{label: "Any", value: "any"}, {label: "Nonstop only", value: "nonstop"}], $/filters/stops)
apply = Button(Text("Apply"), "primary", Event("apply_filters", {maxPrice: $/filters/maxPrice, adults: $/filters/adults, stops: $/filters/stops}))
root = Column([title, dates, who, budget, stops, apply], align="stretch")

---END 20-sidebar-refine---

---BEGIN 30-home-dashboard---
# Home: a generative dashboard, reassembled for what matters today.
# Stat tiles first, then the thing that needs a decision, then context.
surface("home")
hello = Text("17 days to Madrid", variant="h1")
t1 = StatTile("Booked", "3 of 5", caption="flights, hotel, transfer", tone="positive")
t2 = StatTile("Budget left", "$680", caption="of $2,000", tone="caution")
t3 = StatTile("Next up", "Pick dinner", caption="Sat 11 Apr", tone="accent", action=Event("open_task", {id: "dinner"}))
tiles = Row([t1, t2, t3])
budget = ProgressMeter("Budget used", 1320, 2000, caption="$1,320 of $2,000", tone="caution")
weather = WeatherStrip([{day: "Sun", high: "21°", low: "9°", condition: "sun"}, {day: "Mon", high: "19°", low: "8°", condition: "sun"}, {day: "Tue", high: "16°", low: "7°", condition: "rain"}], place="Madrid", caption="Pack a light jacket for Tuesday")
map = MapPreview([{label: "Hotel", kind: "stay"}, {label: "Prado", kind: "sight", day: "2"}, {label: "Sobrino", kind: "food", day: "2"}], caption="Everything on day 2 is walkable")
root = Column([hello, tiles, budget, weather, map], align="stretch")

---END 30-home-dashboard---

---BEGIN 40-itinerary-day---
# A day of the itinerary, plus a template-driven packing list bound to data.
surface("itinerary")
$/packing/0/item = "Passport"
$/packing/0/done = true
$/packing/1/item = "Adapter"
$/packing/1/done = false
a1 = ActivityItem("Prado Museum", "10:00", category="sight", location="Paseo del Prado 23", duration="2h", note="Book the timed entry", action=Event("open_activity", {id: "prado"}))
a2 = ActivityItem("Lunch at Sobrino", "13:30", category="food", location="Calle de Cuchilleros 17", duration="1h 30m")
a3 = ActivityItem("Retiro Park", "16:00", category="outdoors", duration="1h 30m", note="Rowboats until 19:00")
day2 = ItineraryDay("Day 2 — Old Madrid", [a1, a2, a3], date="Mon 13 Apr", summary="Art in the morning, a long lunch, green afternoon")
packingRow = CheckBox($item, $done)
packing = List(_template($/packing, packingRow))
packingTitle = Text("Packing", variant="h4")
root = Column([day2, packingTitle, packing])

---END 40-itinerary-day---

---BEGIN 50-traveler-form---
# Several things to set, one button. Every edited path is bound into its context.
surface("inline-traveler")
title = Text("Who is travelling?", variant="h3")
name = TextField("Full name (as on passport)", $/traveler/name)
email = TextField("Email", $/traveler/email, "shortText")
seat = ChoicePicker("Seat", "mutuallyExclusive", [{label: "Window", value: "window"}, {label: "Aisle", value: "aisle"}], $/traveler/seat)
save = Button(Text("Save traveller"), "primary", Event("save_traveler", {name: $/traveler/name, email: $/traveler/email, seat: $/traveler/seat}))
root = Column([title, name, email, seat, save], align="stretch")

---END 50-traveler-form---

---BEGIN 60-incremental-update---
# Changing one value on a surface that is already on screen.
# No components, no root — just the data. The host re-renders in place.
surface("home")
$/home/budgetUsed = 1480
$/home/budgetCaption = "$1,480 of $2,000"

---END 60-incremental-update---
