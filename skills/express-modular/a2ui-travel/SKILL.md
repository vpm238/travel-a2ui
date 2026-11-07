---
name: a2ui-travel
description: UI component catalog signatures for a2ui-travel. Use when building a2ui-travel
  user interface components.
metadata:
  protocol_version: '1.0'
  inference_format: express
  catalogs:
  - a2ui-travel
  catalog_id: https://travel-a2ui.dev/catalogs/a2ui-travel/catalog.json
---

## Positional Component Signatures

Use these exact positional signatures to instantiate components. Do not output property keys:
• ActivityItem(title, time?, category?, location?, duration?, note?, action? (static), done?, onRemove? (static), weight? (static), accessibility? (static))
  - Description: A single scheduled thing inside an ItineraryDay — a meal, a museum, a transfer, a check-in.
  - title: What it is, e.g. 'Prado Museum'.
  - time: Start time as a display string, e.g. '10:00'.
  - category: Drives the icon and colour: one of 'food', 'sight', 'transit', 'stay', 'outdoors', 'shopping', 'event', 'free'. Defaults to 'sight'.
  - location: Where it happens, e.g. 'Paseo del Prado 23'.
  - duration: How long to budget, e.g. '2h'.
  - note: One short practical note, e.g. 'Book the timed entry'.
  - action: Fired when the traveler taps the activity.
  - done: Whether the traveler has ticked this off.
  - onRemove: Fired when the traveler drops this activity. Give every activity one: a day plan is theirs to edit.
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
  - accessibility: Assistive technology: {label, description, live, hidden}.
• AirportPicker(label, value, options, kind? (static), placeholder?, weight? (static), accessibility? (static), checks? (static))
  - Description: A search field for one place — where the trip leaves from or goes to — with a type-ahead list of the places this deployment serves. Use it for an origin or a destination; never a ChoicePicker of airports.
  - label: The question, e.g. 'Where from?'.
  - value: Bound path the chosen option's `value` is written to, e.g. `$/trip/origin`.
  - options: Every place that may be chosen: a list of {value, label, code?, detail?}, or a binding to one, e.g. $/places/origins. `value` is what is stored when chosen ('JFK', 'Madrid'); `label` is the place as a person names it.
  - kind: Which end of the trip this is; sets the icon. Must be one of: 'origin', 'destination'
  - placeholder: Hint in the empty field, e.g. 'City or airport'.
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
  - accessibility: Assistive technology: {label, description, live, hidden}.
• Booked(heading? (static))
  - Description: Every flight chosen on the route, in hop order: the answer to "show me
    my flights".
    
    Binds `/booked`, which the host keeps equal to the fares on the record, so
    nothing is typed out and nothing is left off however many hops there are.
    Each card shows its route and fare, with a `change` action for its hop.
  - heading: Optional line above the list, e.g. 'Your five flights'.
• Button(child (static), variant? (static), action (static), weight? (static), checks? (static))
  - child: The ID of the child component. Use a 'Text' component for a labeled button. Only use an 'Icon' if the requirements explicitly ask for an icon-only button.
  - variant: A hint for the button style. If omitted, a default button style is used. 'primary' indicates this is the main call-to-action button. 'borderless' means the button has no visual border or background, making its child content appear like a clickable link. Must be one of: 'default', 'primary', 'borderless'
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
• CheckBox(label, value, weight? (static), checks? (static))
  - label: The text to display next to the checkbox.
  - value: The current state of the checkbox (true for checked, false for unchecked).
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
• ChoicePicker(label?, variant? (static), options (static), value, displayStyle? (static), filterable? (static), weight? (static), checks? (static))
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
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
• Column(children, justify? (static), align? (static), weight? (static))
  - Description: A layout component that arranges its children vertically. To create a grid layout, nest Rows within this Column.
  - children: Defines the children. Use an array of strings for a fixed set of children, or a template object to generate children from a data list. Children cannot be defined inline, they must be referred to by ID.
  - justify: Defines the arrangement of children along the main axis (vertically). Use 'spaceBetween' to push items to the edges (e.g. header at top, footer at bottom), or 'start'/'end'/'center' to pack them together. Must be one of: 'center', 'end', 'spaceAround', 'spaceBetween', 'spaceEvenly', 'start', 'stretch'
  - align: Defines the alignment of children along the cross axis (horizontally). This is similar to the CSS 'align-items' property. Must be one of: 'start', 'center', 'end', 'stretch'
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
• DateRangePicker(label, start, end, action? (static), nightsLabel?, weight? (static), accessibility? (static), checks? (static))
  - Description: Picks the trip's start and end dates. Both bound values are ISO 8601 calendar dates with no time or offset, e.g. '2026-04-12'.
  - label: What the range is for, e.g. 'When are you going?'.
  - start: Bound path for the start date (yyyy-MM-dd).
  - end: Bound path for the end date (yyyy-MM-dd).
  - action: Fired when the traveler commits a new range.
  - nightsLabel: Derived caption, e.g. '6 nights'.
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
  - accessibility: Assistive technology: {label, description, live, hidden}.
• DateTimeInput(value, enableDate? (static), enableTime? (static), min?, max?, label?, weight? (static), checks? (static))
  - value: The selected date and/or time value in ISO 8601 format. If not yet set, initialize with an empty string.
  - enableDate: If true, allows the user to select a date.
  - enableTime: If true, allows the user to select a time.
  - min: The minimum allowed date/time in ISO 8601 format.
  - max: The maximum allowed date/time in ISO 8601 format.
  - label: The text label for the input field.
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
• ExpenseSplit(title, total, participants (static), action? (static), actionLabel?, weight? (static), accessibility? (static))
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
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
  - accessibility: Assistive technology: {label, description, live, hidden}.
• FlightOption(airline, departTime, arriveTime, origin, destination, price, action (static), duration?, stops?, flightNumber?, cabin? (static), selected?, badge?, total?, weight? (static), accessibility? (static))
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
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
  - accessibility: Assistive technology: {label, description, live, hidden}.
• Flights(heading? (static), selected? (static), hop? (static))
  - Description: A pressable list of the fares `search_flights` returned.
    
    Binds the rows at `/flights`, so draw it before or after the lookup: it
    fills in when the rows land. With `hop`, it binds that hop's own rows
    (`/fares/N`), so several hops' lists drawn in one turn each keep their
    fares; pass the same `hop` to `search_flights`. Each card says airline,
    number, times, stops and price, and pressing one sends `select_flight`
    with the fare's id, price, airline, number, times and airports.
  - heading: Optional line above the list, e.g. 'Outbound · JFK → MAD'.
  - selected: Path holding the chosen fare, e.g. '/trip/selectedFlight', so the chosen card is marked.
  - hop: Which hop these fares are for, counted from one (hop two is the trip's legs/0); the press carries it.
• Highlights(heading? (static))
  - Description: What a destination is worth going for, as `get_destination` returned it.
    
    Binds the rows at `/highlights`; draw it before or after the lookup.
  - heading: Optional line above the list, e.g. 'Worth your time in Berlin'.
• HotelCard(name, price, action (static), imageUrl?, neighborhood?, rating?, amenities?, selected?, badge?, weight? (static), accessibility? (static))
  - Description: A place to stay, presented as a rich card with imagery, rating and nightly price.
  - name: Property name.
  - price: Preformatted nightly or total price, e.g. '$186 / night'.
  - action: Fired when the traveler picks or opens this property.
  - imageUrl: Hero image URL. Omit for a generated placeholder.
  - neighborhood: Where it is, in words a traveler uses, e.g. 'Malasaña'.
  - rating: Rating as a display string, e.g. '4.6 (1,204)'.
  - amenities: Short amenity labels, at most five.
  - selected: Whether this property is currently chosen.
  - badge: Short editorial tag, e.g. 'Walkable' or 'Best value'.
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
  - accessibility: Assistive technology: {label, description, live, hidden}.
• Itinerary(heading? (static))
  - Description: The day plan recorded on the trip, one card per day.
    
    Binds `/days`, which the host keeps equal to the `days` you saved with
    `save_trip`, so record the plan there and draw it with this rather than
    writing every activity out. Each activity can be dropped (`drop_activity`
    with its day and index) and each day can ask for more (`add_activity`).
  - heading: Optional line above the plan, e.g. 'Four days in Berlin'.
• ItineraryDay(title, children, date?, summary?, action? (static), onAdd? (static), weight? (static), accessibility? (static))
  - Description: One day of a trip. Its children are the day's ActivityItem components, in chronological order.
  - title: Day heading, e.g. 'Day 3 — Toledo'.
  - children: The day's activities, earliest first.
  - date: Date as a display string, e.g. 'Tue 14 Apr'.
  - summary: One-line character of the day, e.g. 'Old town, slow pace'.
  - action: Fired when the traveler opens or edits the whole day.
  - onAdd: Fired when the traveler wants something else in this day.
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
  - accessibility: Assistive technology: {label, description, live, hidden}.
• List(children, direction? (static), align? (static), weight? (static))
  - children: Defines the children. Use an array of strings for a fixed set of children, or a template object to generate children from a data list.
  - direction: The direction in which the list items are laid out. Must be one of: 'vertical', 'horizontal'
  - align: Defines the alignment of children along the cross axis. Must be one of: 'start', 'center', 'end', 'stretch'
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
• MapPreview(markers (static), caption?, action? (static), weight? (static), accessibility? (static))
  - Description: A lightweight schematic map of the places in play. Not a live map — it orients the traveler and is safe to render offline.
  - markers: Places to pin. Static values only — the host lays them out relative to each other.
    List of maps keys:
    * label - Short place name shown next to the pin.
    * kind - One of 'stay', 'sight', 'food', 'transit'.
    * day - Optional day number this marker belongs to.
  - caption: One line describing what the map shows.
  - action: Fired when the traveler taps the map.
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
  - accessibility: Assistive technology: {label, description, live, hidden}.
• PriceSummary(lines (static), total, totalLabel?, action? (static), actionLabel?, caption?, weight? (static), accessibility? (static))
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
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
  - accessibility: Assistive technology: {label, description, live, hidden}.
• ProgressMeter(label, value, max, caption?, tone? (static), weight? (static), accessibility? (static))
  - Description: How far along something is — budget spent, packing done, bookings confirmed. `value` and `max` are numbers, not display strings.
  - label: What is progressing.
  - value: Current amount.
  - max: Amount that counts as complete.
  - caption: Reading in words, e.g. '$1,320 of $2,000'.
  - tone: Colour role for the bar. Must be one of: 'neutral', 'positive', 'caution', 'critical', 'accent'
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
  - accessibility: Assistive technology: {label, description, live, hidden}.
• Row(children, justify? (static), align? (static), weight? (static))
  - Description: A layout component that arranges its children horizontally. To create a grid layout, nest Columns within this Row.
  - children: Defines the children. Use an array of strings for a fixed set of children, or a template object to generate children from a data list. Children cannot be defined inline, they must be referred to by ID.
  - justify: Defines the arrangement of children along the main axis (horizontally). Use 'spaceBetween' to push items to the edges, or 'start'/'end'/'center' to pack them together. Must be one of: 'center', 'end', 'spaceAround', 'spaceBetween', 'spaceEvenly', 'start', 'stretch'
  - align: Defines the alignment of children along the cross axis (vertically). This is similar to the CSS 'align-items' property, but uses camelCase values (e.g., 'start'). Must be one of: 'start', 'center', 'end', 'stretch'
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
• Slider(label?, min? (static), max (static), value, steps? (static), weight? (static), checks? (static))
  - label: The label for the slider.
  - min: The minimum value of the slider.
  - max: The maximum value of the slider.
  - value: The current value of the slider.
  - steps: The number of discrete divisions in the slider range. If specified, the slider will snap to discrete values.
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
• StatTile(label, value, caption?, tone? (static), action? (static), weight? (static), accessibility? (static))
  - Description: One number that matters, sized for a dashboard grid. Home-surface staple: days until departure, budget left, bookings confirmed.
  - label: What the number measures.
  - value: The number as a display string, e.g. '17'.
  - caption: Context under the number, e.g. 'until Madrid'.
  - tone: Colour role for the tile. Must be one of: 'neutral', 'positive', 'caution', 'critical', 'accent'
  - action: Fired when the traveler taps the tile.
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
  - accessibility: Assistive technology: {label, description, live, hidden}.
• Stays(heading? (static), selected? (static), hop? (static))
  - Description: A pressable list of the stays `search_hotels` returned.
    
    Binds the rows at `/hotels`; draw it before or after the lookup. With
    `hop`, it binds that hop's own rows (`/rooms/N`); pass the same `hop` to
    `search_hotels`. Pressing a card sends `select_hotel` with the stay's id,
    name and price.
  - heading: Optional line above the list, e.g. 'Stays in Madrid'.
  - selected: Path holding the chosen stay, e.g. '/trip/selectedHotel'.
  - hop: Which hop stays the night, counted from one.
• Text(text, variant? (static), weight? (static))
  - text: The text content to display. While simple Markdown formatting is supported (i.e. without HTML, images, or links), utilizing dedicated UI components is generally preferred for a richer and more structured presentation.
  - variant: A hint for the base text style. Must be one of: 'caption', 'body'
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
• TextField(label, value?, placeholder?, variant? (static), weight? (static), checks? (static))
  - label: The text label for the input field.
  - value: The value of the text field.
  - placeholder: The placeholder text for the input field.
  - variant: The type of input field to display. Must be one of: 'longText', 'number', 'shortText', 'obscured'
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
• TravelerCounter(label, value, min? (static), max? (static), caption?, weight? (static), accessibility? (static), checks? (static))
  - Description: A stepper for party size. Bind `value` so the count survives a re-render and later turns can read it.
  - label: What is being counted, e.g. 'Adults'.
  - value: Bound path holding the current count.
  - min: Lowest allowed count.
  - max: Highest allowed count.
  - caption: Qualifier, e.g. 'Age 12+'.
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
  - accessibility: Assistive technology: {label, description, live, hidden}.
• Trip(heading? (static), money? (static))
  - Description: The trip so far, hop by hop: the standing panel.
    
    Binds `/panel`, which the host keeps current, so it never needs drawing
    again: each hop shows its route, its dates and party, and its fare and stay
    once they are chosen, each with a `change` action naming what and which
    hop. Draw it on the panel, `surface("sidebar")`.
  - heading: Optional line at the top, e.g. 'Your trip to Madrid'.
  - money: True to add what has been committed so far and what is left of the budget, once something is priced.
• TripCalendar(start, end?, marks? (static), title?, caption?, action? (static), weight? (static), accessibility? (static))
  - Description: The trip's dates on a month grid: the travel days drawn as one highlighted band, with a glyph on any day worth marking. Read-only — use it wherever a traveler should *see* when they are going (the panel, the home surface, beside a chosen flight), and DateRangePicker when they are still choosing.
  - start: First travel day as yyyy-MM-dd, e.g. '2027-04-12'. Bind it to the trip — `$/trip/startDate` — so the band moves when the dates do.
  - end: Last travel day as yyyy-MM-dd. Omit for a single day; the band runs from `start` to here inclusive.
  - marks: Days worth a glyph, in date order. Static values only — a departure, a check-in, the one thing booked that day.
    List of maps keys:
    * date - The day, as yyyy-MM-dd.
    * icon - A short glyph for the day: an emoji, or one of 'plane', 'bed', 'food', 'sight', 'transit', 'outdoors', 'event'.
    * label - What the glyph means, e.g. 'Fly out' — shown in the key.
  - title: Heading, e.g. 'Madrid' or 'Six nights in April'.
  - caption: One line under the grid, e.g. '6 nights · flights booked'.
  - action: Fired when the traveler taps the calendar, e.g. to change the dates.
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
  - accessibility: Assistive technology: {label, description, live, hidden}.
• WeatherStrip(days (static), place?, caption?, weight? (static), accessibility? (static))
  - Description: A short forecast row for the destination. Purely informational.
  - days: Forecast entries in date order, at most seven. Static values only.
    List of maps keys:
    * day - Short day label, e.g. 'Tue'.
    * high - High temperature as a display string, e.g. '21°'.
    * low - Low temperature as a display string.
    * condition - One of 'sun', 'cloud', 'rain', 'storm', 'snow', 'fog'.
  - place: Where the forecast is for.
  - caption: One line of interpretation, e.g. 'Pack a light jacket'.
  - weight: The relative weight of this component within a Row or Column. This is similar to the CSS 'flex-grow' property. Note: this may ONLY be set when the component is a direct descendant of a Row or Column.
  - accessibility: Assistive technology: {label, description, live, hidden}.

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
  - Description: Performs string interpolation of data model values and other functions in the catalog functions list and returns the resulting string. The value string can contain interpolated expressions in the `${expression}` format. Supported expression types include: JSON Pointer paths to the data model (e.g., `${/absolute/path}` or `${relative/path}`), and renderer-side function calls (e.g., `${now()}`). Function arguments must be named (e.g., `${formatDate(value:${/currentDate}, format:'MM-dd')}`). To include a literal `${` sequence, escape it as `\${`.
• openUrl(url)
  - Description: Opens the specified URL in a browser or handler (requires user activation). This function has no return value.
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

Travel components carry meaning the layout primitives do not:

- Prefer a travel component to one assembled from Row, Column and Text: a
  flight is a FlightOption, a night's stay a HotelCard.
- Every option someone could act on has an action. An option that cannot be
  chosen is a picture of one.
- Give every pressable card an accessibility label that reads as a sentence
  ("Iberia IB6250, 18:40 JFK to 08:15 next day MAD, nonstop, $412"): it
  replaces the card's own text for a screen reader, so say all of it. Use
  live: "polite" for a value that updates itself and hidden: true for
  decoration.
- Money is a preformatted display string ("$412", "€1,180 total"), and so are
  times ("07:15", "Tue 14 Apr"). DateRangePicker's values are calendar dates
  ("2026-04-12").
- Bind the current choice of a set of options into the data model so it can
  be read back and marked selected.
- One job per surface.

### Examples:

<a2ui>
surface("inline-1", sendDataModel=true)
title = Text("### Madrid in April — two travellers")
from = AirportPicker("Where from?", $/trip/origin, $/places/origins, "origin", "City or airport")
dates = DateRangePicker("Travel dates", $/trip/startDate, $/trip/endDate, _, formatString("${calcNights(start: ${/trip/startDate}, end: ${/trip/endDate})} nights"))
who = TravelerCounter("Travellers", $/trip/travelers, 1, 8)
go_label = Text("Find flights")
go = Button(go_label, "primary", Event("find_flights", userMessage="Find flights for these dates"))
root = Column([title, from, dates, who, go], _, "stretch")
</a2ui>

<a2ui>
surface("inline-2")
fares = Flights("Outbound · JFK → MAD · Sun 12 Apr", "/trip/selectedFlight")
note = Text("Prices are per traveler, round trip.")
root = Column([fares, note])
</a2ui>

<a2ui>
surface("inline-3", sendDataModel=true)
$/filters/adults = 2
$/filters/maxPrice = 600
title = Text("### Refine")
dates = DateRangePicker("Travel dates", $/filters/start, $/filters/end, Event("dates_changed"), "6 nights")
who = TravelerCounter("Adults", $/filters/adults, 1, 8)
budget = Slider("Max fare", 150, 1500, $/filters/maxPrice)
stops = ChoicePicker("Stops", "mutuallyExclusive", [{label: "Any", value: "any"}, {label: "Nonstop only", value: "nonstop"}], $/filters/stops)
apply = Button(apply_child, "primary", Event("apply_filters", {maxPrice: $/filters/maxPrice, adults: $/filters/adults, stops: $/filters/stops}))
apply_child = Text("Apply")
root = Column([title, dates, who, budget, stops, apply], _, "stretch")
</a2ui>

<a2ui>
surface("sidebar")
panel = Trip("Your trip to Madrid", true)
root = Column([panel])
</a2ui>

<a2ui>
surface("inline-4")
$/packing = [{item: "Passport", done: true}, {item: "Adapter", done: false}]
a1 = ActivityItem("Prado Museum", "10:00", "sight", "Paseo del Prado 23", "2h", "Book the timed entry", Event("open_activity", {id: "prado"}))
a2 = ActivityItem("Lunch at Sobrino", "13:30", "food", "Calle de Cuchilleros 17", "1h 30m")
a3 = ActivityItem("Retiro Park", "16:00", "outdoors", _, "1h 30m", "Rowboats until 19:00")
day2 = ItineraryDay("Day 2 — Old Madrid", [a1, a2, a3], "Mon 13 Apr", "Art in the morning, a long lunch, green afternoon")
packingRow = CheckBox($item, $done)
packing = List(_template($/packing, packingRow))
packingTitle = Text("#### Packing")
root = Column([day2, packingTitle, packing])
</a2ui>

<a2ui>
surface("home")
hello = Text("# 17 days to Madrid")
t1 = StatTile("Booked", "3 of 5", "flights, hotel, transfer", "positive")
t2 = StatTile("Budget left", "$680", "of $2,000", "caution")
t3 = StatTile("Next up", "Pick dinner", "Sat 11 Apr", "accent", Event("open_task", {id: "dinner"}))
tiles = Row([t1, t2, t3])
budget = ProgressMeter("Budget used", 1320, 2000, "$1,320 of $2,000", "caution")
when = TripCalendar($/trip/startDate, $/trip/endDate, [{date: "2027-04-12", icon: "plane", label: "Fly out"}, {date: "2027-04-18", icon: "plane", label: "Fly home"}], "Madrid", "6 nights")
weather = WeatherStrip([{day: "Sun", high: "21°", low: "9°", condition: "sun"}, {day: "Mon", high: "19°", low: "8°", condition: "sun"}, {day: "Tue", high: "16°", low: "7°", condition: "rain"}], "Madrid", "Pack a light jacket for Tuesday")
map = MapPreview([{label: "Hotel", kind: "stay"}, {label: "Prado", kind: "sight", day: "2"}, {label: "Sobrino", kind: "food", day: "2"}], "Everything on day 2 is walkable")
root = Column([hello, tiles, budget, when, weather, map], _, "stretch")
</a2ui>

<a2ui>
surface("inline-5", sendDataModel=true)
title = Text("### Who is travelling?")
name = TextField("Full name (as on passport)", $/traveler/name)
email = TextField("Email", $/traveler/email, "shortText")
seat = ChoicePicker("Seat", "mutuallyExclusive", [{label: "Window", value: "window"}, {label: "Aisle", value: "aisle"}], $/traveler/seat)
save = Button(save_child, "primary", Event("save_traveler", {name: $/traveler/name, email: $/traveler/email, seat: $/traveler/seat}))
save_child = Text("Save traveller")
root = Column([title, name, email, seat, save], _, "stretch")
</a2ui>
