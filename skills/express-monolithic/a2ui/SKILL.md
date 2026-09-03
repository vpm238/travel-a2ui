---
name: a2ui
description: "Plans trips as interactive UI: flight and hotel options, day-by-day itineraries, price breakdowns, and trip dashboards."
metadata:
  protocol_version: "0.9.1"
  inference_format: express
  catalogs:
    - a2ui-travel
  catalog_id: https://travel-a2ui.dev/catalogs/a2ui-travel/catalog.json
---

# A2UI Express output contract

When you show the user an interface, write it in A2UI Express and wrap the whole
block in the sentinel tags `<a2ui>` and `</a2ui>`. Everything outside those tags
is ordinary prose the user reads; everything inside is compiled into A2UI JSON
envelopes and drawn on screen. Never describe an interface in prose that you
could draw.

## Grammar

1. **Components are constructor calls.** Assign one to a variable, or nest it
   inline inside a parent's argument list:

       header = Text("Madrid", variant="h1")
       root = Column([header, Button(Text("Go"), action=Event("go"))])

   Variable names start with a letter or underscore and contain only letters,
   digits and underscores. A variable name becomes the component's id, so name
   things the way you would in code.

2. **`root` is the entry point.** Every surface needs exactly one variable
   called `root`. It is the top of the tree; everything else is reachable from
   it.

3. **Arguments are positional by default**, in the order given in the signatures
   below. Pass them by name (`variant="primary"`) when that is clearer, and use
   `_` to skip an optional argument you do not want but need to step over:

       Image("https://…/a.png", _, "cover")

   Do not pass the same argument both positionally and by name.

4. **Primitives.** Strings use `"…"` or `"""…"""`, with `\n`, `\t`, `\\`
   and `\"` escapes; prefix with `r` for a raw string. Numbers are bare
   (`42`, `-3.5`). Booleans are `true` / `false`. Absent is `null`. Date-time
   values are RFC 3339 with an offset: `"2026-04-12T00:00:00Z"`.

5. **Lists** are `[a, b, c]`. **Maps** are `{title: "Overview", child: body}`.
   Map keys are literal.

6. **Data bindings** start with `$`. An absolute path reads the surface's data
   model — `$/trip/adults`. A relative path reads the current item inside a list
   template — `$name`. A lone `$` is the item itself.

7. **Assign into the data model** by writing to a path:

       $/trip/adults = 2
       $/trip/destination = "Madrid"

   Bind a control's value to a path and the host writes the user's input back
   there, where your next turn can read it.

8. **Actions** are `Event("name", {key: value})`. The event name is what comes
   back to you; the context map is what comes back with it. Bind context values
   to paths so you receive what the user actually chose:

       Event("book_flight", {flightId: "IB6250", adults: $/trip/adults})

9. **Validation** uses `?rule`, written as an extra argument on the field it
   guards. The field's own bound value is the implicit subject, and a trailing
   string is the message shown on failure:

       TextField("Email", $/traveler/email, ?required, ?email("Check that address"))

10. **List templates** repeat one component over a bound list:

        row = Text($title)
        list = List(_template($/activities, row))

11. **Surfaces.** `surface("id")` says which surface the block targets; without
    it the block goes to the host's default surface for this turn. Write to the
    same id again to replace that surface, and `deleteSurface("id")` to remove
    it.

12. **`(static)` arguments take literals only.** They are marked in the
    signatures. Passing a `$` binding to one is a compile error.

13. **Required `action` arguments are required.** If nothing sensible should
    happen yet, pass `Event("noop")` rather than omitting it.

## Streaming

Your output is compiled as it arrives, not after you stop. That has two
consequences worth writing for:

- **Order matters.** Define children before the parent that lists them, and put
  `root` last. The surface then fills in from the top instead of appearing all
  at once at the end.
- **Finish the block.** Close with `</a2ui>` before you go back to prose. An
  unterminated block still renders, but the host cannot tell it is done.

## What the host does with it

Express compiles to A2UI messages: a `createSurface` naming the surface and its
catalog, an `updateComponents` carrying the flattened component tree, and an
`updateDataModel` carrying whatever you assigned to `$` paths. You never write
those envelopes yourself — write Express and let the compiler produce them.

## Positional Component Signatures

Use these exact positional signatures to instantiate components. Do not output property keys:
• ActivityItem(title, time?, category? (static), location?, duration?, note?, action? (static), done?)
  - Description: A single scheduled thing inside an ItineraryDay — a meal, a museum, a transfer, a check-in.
  - title: What it is, e.g. 'Prado Museum'.
  - time: Start time as a display string, e.g. '10:00'.
  - category: Drives the icon and colour the host uses. Must be one of: 'food', 'sight', 'transit', 'stay', 'outdoors', 'shopping', 'event', 'free'
  - location: Where it happens, e.g. 'Paseo del Prado 23'.
  - duration: How long to budget, e.g. '2h'.
  - note: One short practical note, e.g. 'Book the timed entry'.
  - action: Fired when the traveler taps the activity.
  - done: Whether the traveler has ticked this off.
• AudioPlayer(url, description?)
  - url: The URL of the audio to be played.
  - description: A description of the audio, such as a title or summary.
• Button(child (component ID), variant? (static), action (static), checks? (static))
  - child: The ID of the child component. Use a 'Text' component for a labeled button. Only use an 'Icon' if the requirements explicitly ask for an icon-only button.
  - variant: A hint for the button style. If omitted, a default button style is used. 'primary' indicates this is the main call-to-action button. 'borderless' means the button has no visual border or background, making its child content appear like a clickable link. Must be one of: 'default', 'primary', 'borderless'
• Card(child (component ID))
  - child: The ID of the single child component to be rendered inside the card. To display multiple elements, you MUST wrap them in a layout component (like Column or Row) and pass that container's ID here. Do NOT pass multiple IDs or a non-existent ID.
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
• DateTimeInput(value, enableDate? (static), enableTime? (static), min?, max?, label?, checks? (static))
  - value: The selected date and/or time value in ISO 8601 format. If not yet set, initialize with an empty string.
  - enableDate: If true, allows the user to select a date.
  - enableTime: If true, allows the user to select a time.
  - min: The minimum allowed date/time in ISO 8601 format.
  - max: The maximum allowed date/time in ISO 8601 format.
  - label: The text label for the input field.
• Divider(axis? (static))
  - axis: The orientation of the divider. Must be one of: 'horizontal', 'vertical'
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
• FlightOption(airline, departTime, arriveTime, origin, destination, price, action (static), duration?, stops?, flightNumber?, cabin? (static), selected?, badge?)
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
• Icon(name)
  - name: The name of the icon to display. Must be one of: 'accountCircle', 'add', 'arrowBack', 'arrowForward', 'attachFile', 'calendarToday', 'call', 'camera', 'check', 'close', 'delete', 'download', 'edit', 'event', 'error', 'fastForward', 'favorite', 'favoriteOff', 'folder', 'help', 'home', 'info', 'locationOn', 'lock', 'lockOpen', 'mail', 'menu', 'moreVert', 'moreHoriz', 'notificationsOff', 'notifications', 'pause', 'payment', 'person', 'phone', 'photo', 'play', 'print', 'refresh', 'rewind', 'search', 'send', 'settings', 'share', 'shoppingCart', 'skipNext', 'skipPrevious', 'star', 'starHalf', 'starOff', 'stop', 'upload', 'visibility', 'visibilityOff', 'volumeDown', 'volumeMute', 'volumeOff', 'volumeUp', 'warning'
• Image(url, description?, fit? (static), variant? (static))
  - url: The URL of the image to display.
  - description: Accessibility text for the image.
  - fit: Specifies how the image should be resized to fit its container. This corresponds to the CSS 'object-fit' property. Must be one of: 'contain', 'cover', 'fill', 'none', 'scaleDown'
  - variant: A hint for the image size and style. Must be one of: 'icon', 'avatar', 'smallFeature', 'mediumFeature', 'largeFeature', 'header'
• ItineraryDay(title, children, date?, summary?, action? (static))
  - Description: One day of a trip. Its children are the day's ActivityItem components, in chronological order.
  - title: Day heading, e.g. 'Day 3 — Toledo'.
  - children: The day's activities, earliest first.
  - date: Date as a display string, e.g. 'Tue 14 Apr'.
  - summary: One-line character of the day, e.g. 'Old town, slow pace'.
  - action: Fired when the traveler opens or edits the whole day.
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
• Modal(trigger (component ID), content (component ID))
  - trigger: The ID of the component that opens the modal when interacted with (e.g., a button).
  - content: The ID of the component to be displayed inside the modal.
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
• Tabs(tabs (static))
  - tabs: An array of objects, where each object defines a tab with a title and a child component.
    List of maps keys:
    * title - The tab title.
    * child - The ID of the child component.
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
• Video(url)
  - url: The URL of the video to display.
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
• and(values)
  - Description: Performs a logical AND operation on a list of boolean values.
  - values: The list of boolean values to evaluate.
• email(value)
  - Description: Checks that the value is a valid email address.
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
• length(value, min?, max?)
  - Description: Checks string length constraints.
  - min: The minimum allowed length.
  - max: The maximum allowed length.
• not(value)
  - Description: Performs a logical NOT operation on a boolean value.
  - value: The boolean value to negate.
• numeric(value, min?, max?)
  - Description: Checks numeric range constraints.
  - min: The minimum allowed value.
  - max: The maximum allowed value.
• openUrl(url)
  - Description: Opens the specified URL in a browser or handler. This function has no return value.
  - url: The URL to open.
• or(values)
  - Description: Performs a logical OR operation on a list of boolean values.
  - values: The list of boolean values to evaluate.
• pluralize(value, zero?, one?, two?, few?, many?, other)
  - Description: Returns a localized string based on the Common Locale Data Repository (CLDR) plural category of the count (zero, one, two, few, many, other). Requires an 'other' fallback. For English, just use 'one' and 'other'.
  - value: The numeric value used to determine the plural category.
  - zero: String for the 'zero' category (e.g., 0 items).
  - one: String for the 'one' category (e.g., 1 item).
  - two: String for the 'two' category (used in Arabic, Welsh, etc.).
  - few: String for the 'few' category (e.g., small groups in Slavic languages).
  - many: String for the 'many' category (e.g., large groups in various languages).
  - other: The default/fallback string (used for general plural cases).
• regex(value, pattern)
  - Description: Checks that the value matches a regular expression string.
  - pattern: The regex pattern to match against.
• required(value)
  - Description: Checks that the value is not null, undefined, or empty.
  - value: The value to check.

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

## Examples

**Inline: answering "find me a flight to Madrid" inside the chat feed. One surface, one job — three options and a way to pick one.**

```
<a2ui>
surface("inline-flights")
$/trip/selectedOutbound = ""
heading = Text("Outbound · JFK → MAD · Sun 12 Apr", variant="h3")
f1 = FlightOption("Iberia", "18:40", "08:15 +1", "JFK", "MAD", "$412", Event("select_flight", {id: "IB6250", price: "$412"}), duration="7h 35m", stops="Nonstop", flightNumber="IB6250", selected=$/trip/selectedOutbound, badge="Cheapest")
f2 = FlightOption("Delta", "21:10", "10:50 +1", "JFK", "MAD", "$468", Event("select_flight", {id: "DL126", price: "$468"}), duration="7h 40m", stops="Nonstop", flightNumber="DL126")
f3 = FlightOption("TAP", "17:25", "11:05 +1", "JFK", "MAD", "$367", Event("select_flight", {id: "TP208", price: "$367"}), duration="11h 40m", stops="1 stop · LIS", flightNumber="TP208", badge="Lowest fare")
note = Text("Prices are per traveler, round trip.")
root = Column([heading, f1, f2, f3, note])
</a2ui>
```

**Sidebar: controls that refine the trip currently in focus. The sidebar is a persistent surface — target it by id and it replaces itself.**

```
<a2ui>
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
</a2ui>
```

**Home: a generative dashboard, reassembled for what matters today. Stat tiles first, then the thing that needs a decision, then context.**

```
<a2ui>
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
</a2ui>
```

**A day of the itinerary, plus a template-driven packing list bound to data.**

```
<a2ui>
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
</a2ui>
```

**A form the host validates locally — checks travel with the field they guard.**

```
<a2ui>
surface("inline-traveler")
title = Text("Who is travelling?", variant="h3")
name = TextField("Full name (as on passport)", $/traveler/name, ?required("We need the name on the passport"))
email = TextField("Email", $/traveler/email, "shortText", ?required, ?email)
seat = ChoicePicker("Seat", "mutuallyExclusive", [{label: "Window", value: "window"}, {label: "Aisle", value: "aisle"}], $/traveler/seat)
save = Button(Text("Save traveller"), "primary", Event("save_traveler", {name: $/traveler/name, email: $/traveler/email, seat: $/traveler/seat}))
root = Column([title, name, email, seat, save], align="stretch")
</a2ui>
```

**Changing one value on a surface that is already on screen. No components, no root — just the data. The host re-renders in place.**

```
<a2ui>
surface("home")
$/home/budgetUsed = 1480
$/home/budgetCaption = "$1,480 of $2,000"
</a2ui>
```
