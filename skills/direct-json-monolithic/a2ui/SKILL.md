---
name: a2ui
description: "Plans trips as interactive UI: flight and hotel options, day-by-day itineraries, price breakdowns, and trip dashboards."
metadata:
  protocol_version: "0.9.1"
  inference_format: direct_json
  catalogs:
    - a2ui-travel
  catalog_id: https://travel-a2ui.dev/catalogs/a2ui-travel/catalog.json
---

# A2UI JSON output contract

When you show the user an interface, emit A2UI protocol messages as a JSON array
wrapped in the sentinel tags `<a2ui>` and `</a2ui>`. Everything outside those
tags is prose the user reads.

## Message envelopes

Emit an array of messages. Three kinds matter:

```json
[
  {"version": "v0.9.1", "createSurface": {"surfaceId": "inline-1", "catalogId": "<catalog id>"}},
  {"version": "v0.9.1", "updateComponents": {"surfaceId": "inline-1", "components": [ ... ]}},
  {"version": "v0.9.1", "updateDataModel": {"surfaceId": "inline-1", "path": "/", "value": { ... }}}
]
```

- `createSurface` opens a surface and names the catalog its components come from.
- `updateComponents` carries the component tree, flattened.
- `updateDataModel` seeds the values components bind to. Send it alone to change
  what is already on screen without redrawing it.
- `deleteSurface` — `{"version": "v0.9.1", "deleteSurface": {"surfaceId": "…"}}` — removes a surface.

## Components

The tree is an **adjacency list**, not nested objects. Every component is a flat
entry with its own `id`, and a parent refers to children by id:

```json
{"id": "root", "component": "Column", "children": ["title", "cta"]}
{"id": "title", "component": "Text", "text": "Madrid in April", "variant": "h1"}
{"id": "cta", "component": "Button", "child": "ctaLabel", "variant": "primary",
 "action": {"event": {"name": "book", "context": {"id": "IB6250"}}}}
{"id": "ctaLabel", "component": "Text", "text": "Book"}
```

Rules that are not optional:

1. Exactly one component has `id: "root"`. It is the top of the tree.
2. Every id referenced by a parent must exist in the same `components` array.
3. **Data binding** is `{"path": "/trip/adults"}` in place of a literal value.
   Paths are absolute from the data model root, or relative inside a list
   template.
4. **Actions** are `{"event": {"name": "…", "context": {…}}}`. Context values may
   be bindings, so you receive what the user chose.
5. **List templates** replace a `children` array with
   `{"path": "/activities", "componentId": "activityRow"}`; the referenced
   component is rendered once per item, with relative paths resolving inside it.
6. **Validation** is a `checks` array on the field it guards:
   `{"condition": {"call": "required", "args": {"value": {"path": "/x"}}}, "message": "…"}`.
7. Properties marked `(static)` below take literal values only — never a
   `{"path": …}` binding.

## Emitting

Emit the array in one piece and close the block with `</a2ui>`. Unlike the
Express format, a partial JSON array cannot be rendered, so do not narrate
between messages.

## Components

Each entry lists the component's properties. `!` marks a required property, `(static)` one that cannot take a data binding, and `(component ID)` one that refers to another component by id.

• ActivityItem: title!, time, category (static) = food|sight|transit|stay|outdoors|shopping|event|free, location, duration, note, action (static), done
  - A single scheduled thing inside an ItineraryDay — a meal, a museum, a transfer, a check-in.
• AudioPlayer: url!, description
• Button: child! (component ID), variant (static) = default|primary|borderless, action! (static), checks (static)
• Card: child! (component ID)
• CheckBox: label!, value!, checks (static)
• ChoicePicker: label, variant (static) = multipleSelection|mutuallyExclusive, options! (static), value!, displayStyle (static) = checkbox|chips, filterable (static), checks (static)
  - A component that allows selecting one or more options from a list.
• Column: children!, justify (static) = start|center|end|spaceBetween|spaceAround|spaceEvenly|stretch, align (static) = center|end|start|stretch
  - A layout component that arranges its children vertically. To create a grid layout, nest Rows within this Column.
• DateRangePicker: label!, start!, end!, action (static), nightsLabel, checks (static)
  - Picks the trip's start and end dates. Both bound values are RFC 3339 timestamps with an offset, e.g. '2026-04-12T00:00:00Z'.
• DateTimeInput: value!, enableDate (static), enableTime (static), min, max, label, checks (static)
• Divider: axis (static) = horizontal|vertical
• ExpenseSplit: title!, total!, participants! (static), action (static), actionLabel
  - Splits a shared trip cost between travelers and shows who owes what.
• FlightOption: airline!, departTime!, arriveTime!, origin!, destination!, price!, action! (static), duration, stops, flightNumber, cabin (static) = economy|premium|business|first, selected, badge
  - A single selectable flight itinerary leg. Use one per option when presenting a choice of flights; do not build flight rows by hand out of Row and Text.
• HotelCard: name!, price!, action! (static), imageUrl, neighborhood, rating, amenities (static), selected, badge
  - A place to stay, presented as a rich card with imagery, rating and nightly price.
• Icon: name! = accountCircle|add|arrowBack|arrowForward|attachFile|calendarToday|call|camera|check|close|delete|download|edit|event|error|fastForward|favorite|favoriteOff|folder|help|home|info|locationOn|lock|lockOpen|mail|menu|moreVert|moreHoriz|notificationsOff|notifications|pause|payment|person|phone|photo|play|print|refresh|rewind|search|send|settings|share|shoppingCart|skipNext|skipPrevious|star|starHalf|starOff|stop|upload|visibility|visibilityOff|volumeDown|volumeMute|volumeOff|volumeUp|warning
• Image: url!, description, fit (static) = contain|cover|fill|none|scaleDown, variant (static) = icon|avatar|smallFeature|mediumFeature|largeFeature|header
• ItineraryDay: title!, children!, date, summary, action (static)
  - One day of a trip. Its children are the day's ActivityItem components, in chronological order.
• List: children!, direction (static) = vertical|horizontal, align (static) = start|center|end|stretch
• MapPreview: markers! (static), caption, action (static)
  - A lightweight schematic map of the places in play. Not a live map — it orients the traveler and is safe to render offline.
• Modal: trigger! (component ID), content! (component ID)
• PriceSummary: lines! (static), total!, totalLabel, action (static), actionLabel, caption
  - The money view: an itemized breakdown and a total. Use this instead of a hand-built table whenever you show what a trip costs.
• ProgressMeter: label!, value!, max!, caption, tone (static) = neutral|positive|caution|critical|accent
  - How far along something is — budget spent, packing done, bookings confirmed. `value` and `max` are numbers, not display strings.
• Row: children!, justify (static) = center|end|spaceAround|spaceBetween|spaceEvenly|start|stretch, align (static) = start|center|end|stretch
  - A layout component that arranges its children horizontally. To create a grid layout, nest Columns within this Row.
• Slider: label, min (static), max! (static), value!, checks (static)
• StatTile: label!, value!, caption, tone (static) = neutral|positive|caution|critical|accent, action (static)
  - One number that matters, sized for a dashboard grid. Home-surface staple: days until departure, budget left, bookings confirmed.
• Tabs: tabs! (static)
• Text: text!, variant (static) = h1|h2|h3|h4|h5|caption|body
• TextField: label!, value, variant (static) = longText|number|shortText|obscured, validationRegexp (static), checks (static)
• TravelerCounter: label!, value!, min (static), max (static), caption, checks (static)
  - A stepper for party size. Bind `value` so the count survives a re-render and later turns can read it.
• Video: url!
• WeatherStrip: days! (static), place, caption
  - A short forecast row for the destination. Purely informational.

## Functions

Used in `checks` conditions and dynamic values.

• and(values!)
  - Performs a logical AND operation on a list of boolean values.
• email(value!)
  - Checks that the value is a valid email address.
• formatCurrency(value!, currency!, decimals, grouping)
  - Formats a number as a currency string.
• formatDate(value!, format!)
  - Formats a timestamp into a string using a pattern.
• formatNumber(value!, decimals, grouping)
  - Formats a number with the specified grouping and decimal precision.
• formatString(value!)
  - Performs string interpolation of data model values and other functions in the catalog functions list and returns the resulting string. The value string can contain interpolated expressions in the `${expression}` format. Supported expression types include: JSON Pointer paths to the data model (e.g., `${/absolute/path}` or `${relative/path}`), and client-side function calls (e.g., `${now()}`). Function arguments must be named (e.g., `${formatDate(value:${/currentDate}, format:'MM-dd')}`). To include a literal `${` sequence, escape it as `\${`.
• length(value!, min, max)
  - Checks string length constraints.
• not(value!)
  - Performs a logical NOT operation on a boolean value.
• numeric(value!, min, max)
  - Checks numeric range constraints.
• openUrl(url!)
  - Opens the specified URL in a browser or handler. This function has no return value.
• or(values!)
  - Performs a logical OR operation on a list of boolean values.
• pluralize(value!, zero, one, two, few, many, other!)
  - Returns a localized string based on the Common Locale Data Repository (CLDR) plural category of the count (zero, one, two, few, many, other). Requires an 'other' fallback. For English, just use 'one' and 'other'.
• regex(value!, pattern!)
  - Checks that the value matches a regular expression string.
• required(value!)
  - Checks that the value is not null, undefined, or empty.

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

```json
[
  {
    "version": "v0.9.1",
    "createSurface": {
      "surfaceId": "inline-flights",
      "catalogId": "https://travel-a2ui.dev/catalogs/a2ui-travel/catalog.json"
    }
  },
  {
    "version": "v0.9.1",
    "updateComponents": {
      "surfaceId": "inline-flights",
      "components": [
        {
          "id": "heading",
          "component": "Text",
          "text": "Outbound · JFK → MAD · Sun 12 Apr",
          "variant": "h3"
        },
        {
          "id": "f1",
          "component": "FlightOption",
          "airline": "Iberia",
          "departTime": "18:40",
          "arriveTime": "08:15 +1",
          "origin": "JFK",
          "destination": "MAD",
          "price": "$412",
          "action": {
            "event": {
              "name": "select_flight",
              "context": {
                "id": "IB6250",
                "price": "$412"
              }
            }
          },
          "duration": "7h 35m",
          "stops": "Nonstop",
          "flightNumber": "IB6250",
          "selected": {
            "path": "/trip/selectedOutbound"
          },
          "badge": "Cheapest"
        },
        {
          "id": "f2",
          "component": "FlightOption",
          "airline": "Delta",
          "departTime": "21:10",
          "arriveTime": "10:50 +1",
          "origin": "JFK",
          "destination": "MAD",
          "price": "$468",
          "action": {
            "event": {
              "name": "select_flight",
              "context": {
                "id": "DL126",
                "price": "$468"
              }
            }
          },
          "duration": "7h 40m",
          "stops": "Nonstop",
          "flightNumber": "DL126"
        },
        {
          "id": "f3",
          "component": "FlightOption",
          "airline": "TAP",
          "departTime": "17:25",
          "arriveTime": "11:05 +1",
          "origin": "JFK",
          "destination": "MAD",
          "price": "$367",
          "action": {
            "event": {
              "name": "select_flight",
              "context": {
                "id": "TP208",
                "price": "$367"
              }
            }
          },
          "duration": "11h 40m",
          "stops": "1 stop · LIS",
          "flightNumber": "TP208",
          "badge": "Lowest fare"
        },
        {
          "id": "note",
          "component": "Text",
          "text": "Prices are per traveler, round trip."
        },
        {
          "id": "root",
          "component": "Column",
          "children": [
            "heading",
            "f1",
            "f2",
            "f3",
            "note"
          ]
        }
      ]
    }
  },
  {
    "version": "v0.9.1",
    "updateDataModel": {
      "surfaceId": "inline-flights",
      "path": "/",
      "value": {
        "trip": {
          "selectedOutbound": ""
        }
      }
    }
  }
]
```

**Sidebar: controls that refine the trip currently in focus. The sidebar is a persistent surface — target it by id and it replaces itself.**

```json
[
  {
    "version": "v0.9.1",
    "createSurface": {
      "surfaceId": "sidebar",
      "catalogId": "https://travel-a2ui.dev/catalogs/a2ui-travel/catalog.json"
    }
  },
  {
    "version": "v0.9.1",
    "updateComponents": {
      "surfaceId": "sidebar",
      "components": [
        {
          "id": "title",
          "component": "Text",
          "text": "Refine",
          "variant": "h3"
        },
        {
          "id": "dates",
          "component": "DateRangePicker",
          "label": "Travel dates",
          "start": {
            "path": "/filters/start"
          },
          "end": {
            "path": "/filters/end"
          },
          "action": {
            "event": {
              "name": "dates_changed",
              "context": {}
            }
          },
          "nightsLabel": "6 nights"
        },
        {
          "id": "who",
          "component": "TravelerCounter",
          "label": "Adults",
          "value": {
            "path": "/filters/adults"
          },
          "min": 1,
          "max": 8
        },
        {
          "id": "budget",
          "component": "Slider",
          "label": "Max fare",
          "min": 150,
          "max": 1500,
          "value": {
            "path": "/filters/maxPrice"
          }
        },
        {
          "id": "stops",
          "component": "ChoicePicker",
          "label": "Stops",
          "variant": "mutuallyExclusive",
          "options": [
            {
              "label": "Any",
              "value": "any"
            },
            {
              "label": "Nonstop only",
              "value": "nonstop"
            }
          ],
          "value": {
            "path": "/filters/stops"
          }
        },
        {
          "id": "apply",
          "component": "Button",
          "child": "_inline_1",
          "variant": "primary",
          "action": {
            "event": {
              "name": "apply_filters",
              "context": {
                "maxPrice": {
                  "path": "/filters/maxPrice"
                },
                "adults": {
                  "path": "/filters/adults"
                },
                "stops": {
                  "path": "/filters/stops"
                }
              }
            }
          }
        },
        {
          "id": "root",
          "component": "Column",
          "children": [
            "title",
            "dates",
            "who",
            "budget",
            "stops",
            "apply"
          ],
          "align": "stretch"
        },
        {
          "id": "_inline_1",
          "component": "Text",
          "text": "Apply"
        }
      ]
    }
  },
  {
    "version": "v0.9.1",
    "updateDataModel": {
      "surfaceId": "sidebar",
      "path": "/",
      "value": {
        "filters": {
          "maxPrice": 600,
          "adults": 2
        }
      }
    }
  }
]
```

**Home: a generative dashboard, reassembled for what matters today. Stat tiles first, then the thing that needs a decision, then context.**

```json
[
  {
    "version": "v0.9.1",
    "createSurface": {
      "surfaceId": "home",
      "catalogId": "https://travel-a2ui.dev/catalogs/a2ui-travel/catalog.json"
    }
  },
  {
    "version": "v0.9.1",
    "updateComponents": {
      "surfaceId": "home",
      "components": [
        {
          "id": "hello",
          "component": "Text",
          "text": "17 days to Madrid",
          "variant": "h1"
        },
        {
          "id": "t1",
          "component": "StatTile",
          "label": "Booked",
          "value": "3 of 5",
          "caption": "flights, hotel, transfer",
          "tone": "positive"
        },
        {
          "id": "t2",
          "component": "StatTile",
          "label": "Budget left",
          "value": "$680",
          "caption": "of $2,000",
          "tone": "caution"
        },
        {
          "id": "t3",
          "component": "StatTile",
          "label": "Next up",
          "value": "Pick dinner",
          "caption": "Sat 11 Apr",
          "tone": "accent",
          "action": {
            "event": {
              "name": "open_task",
              "context": {
                "id": "dinner"
              }
            }
          }
        },
        {
          "id": "tiles",
          "component": "Row",
          "children": [
            "t1",
            "t2",
            "t3"
          ]
        },
        {
          "id": "budget",
          "component": "ProgressMeter",
          "label": "Budget used",
          "value": 1320,
          "max": 2000,
          "caption": "$1,320 of $2,000",
          "tone": "caution"
        },
        {
          "id": "weather",
          "component": "WeatherStrip",
          "days": [
            {
              "day": "Sun",
              "high": "21°",
              "low": "9°",
              "condition": "sun"
            },
            {
              "day": "Mon",
              "high": "19°",
              "low": "8°",
              "condition": "sun"
            },
            {
              "day": "Tue",
              "high": "16°",
              "low": "7°",
              "condition": "rain"
            }
          ],
          "place": "Madrid",
          "caption": "Pack a light jacket for Tuesday"
        },
        {
          "id": "map",
          "component": "MapPreview",
          "markers": [
            {
              "label": "Hotel",
              "kind": "stay"
            },
            {
              "label": "Prado",
              "kind": "sight",
              "day": "2"
            },
            {
              "label": "Sobrino",
              "kind": "food",
              "day": "2"
            }
          ],
          "caption": "Everything on day 2 is walkable"
        },
        {
          "id": "root",
          "component": "Column",
          "children": [
            "hello",
            "tiles",
            "budget",
            "weather",
            "map"
          ],
          "align": "stretch"
        }
      ]
    }
  }
]
```

**A day of the itinerary, plus a template-driven packing list bound to data.**

```json
[
  {
    "version": "v0.9.1",
    "createSurface": {
      "surfaceId": "itinerary",
      "catalogId": "https://travel-a2ui.dev/catalogs/a2ui-travel/catalog.json"
    }
  },
  {
    "version": "v0.9.1",
    "updateComponents": {
      "surfaceId": "itinerary",
      "components": [
        {
          "id": "a1",
          "component": "ActivityItem",
          "title": "Prado Museum",
          "time": "10:00",
          "category": "sight",
          "location": "Paseo del Prado 23",
          "duration": "2h",
          "note": "Book the timed entry",
          "action": {
            "event": {
              "name": "open_activity",
              "context": {
                "id": "prado"
              }
            }
          }
        },
        {
          "id": "a2",
          "component": "ActivityItem",
          "title": "Lunch at Sobrino",
          "time": "13:30",
          "category": "food",
          "location": "Calle de Cuchilleros 17",
          "duration": "1h 30m"
        },
        {
          "id": "a3",
          "component": "ActivityItem",
          "title": "Retiro Park",
          "time": "16:00",
          "category": "outdoors",
          "duration": "1h 30m",
          "note": "Rowboats until 19:00"
        },
        {
          "id": "day2",
          "component": "ItineraryDay",
          "title": "Day 2 — Old Madrid",
          "children": [
            "a1",
            "a2",
            "a3"
          ],
          "date": "Mon 13 Apr",
          "summary": "Art in the morning, a long lunch, green afternoon"
        },
        {
          "id": "packingRow",
          "component": "CheckBox",
          "label": {
            "path": "item"
          },
          "value": {
            "path": "done"
          }
        },
        {
          "id": "packing",
          "component": "List",
          "children": {
            "path": "/packing",
            "componentId": "packingRow"
          }
        },
        {
          "id": "packingTitle",
          "component": "Text",
          "text": "Packing",
          "variant": "h4"
        },
        {
          "id": "root",
          "component": "Column",
          "children": [
            "day2",
            "packingTitle",
            "packing"
          ]
        }
      ]
    }
  },
  {
    "version": "v0.9.1",
    "updateDataModel": {
      "surfaceId": "itinerary",
      "path": "/",
      "value": {
        "packing": {
          "0": {
            "item": "Passport",
            "done": true
          },
          "1": {
            "item": "Adapter",
            "done": false
          }
        }
      }
    }
  }
]
```

**A form the host validates locally — checks travel with the field they guard.**

```json
[
  {
    "version": "v0.9.1",
    "createSurface": {
      "surfaceId": "inline-traveler",
      "catalogId": "https://travel-a2ui.dev/catalogs/a2ui-travel/catalog.json"
    }
  },
  {
    "version": "v0.9.1",
    "updateComponents": {
      "surfaceId": "inline-traveler",
      "components": [
        {
          "id": "title",
          "component": "Text",
          "text": "Who is travelling?",
          "variant": "h3"
        },
        {
          "id": "name",
          "component": "TextField",
          "label": "Full name (as on passport)",
          "value": {
            "path": "/traveler/name"
          },
          "checks": [
            {
              "condition": {
                "call": "required",
                "args": {
                  "value": {
                    "path": "/traveler/name"
                  }
                }
              },
              "message": "We need the name on the passport"
            }
          ]
        },
        {
          "id": "email",
          "component": "TextField",
          "label": "Email",
          "value": {
            "path": "/traveler/email"
          },
          "variant": "shortText",
          "checks": [
            {
              "condition": {
                "call": "required",
                "args": {
                  "value": {
                    "path": "/traveler/email"
                  }
                }
              },
              "message": "Required check failed"
            },
            {
              "condition": {
                "call": "email",
                "args": {
                  "value": {
                    "path": "/traveler/email"
                  }
                }
              },
              "message": "Email check failed"
            }
          ]
        },
        {
          "id": "seat",
          "component": "ChoicePicker",
          "label": "Seat",
          "variant": "mutuallyExclusive",
          "options": [
            {
              "label": "Window",
              "value": "window"
            },
            {
              "label": "Aisle",
              "value": "aisle"
            }
          ],
          "value": {
            "path": "/traveler/seat"
          }
        },
        {
          "id": "save",
          "component": "Button",
          "child": "_inline_1",
          "variant": "primary",
          "action": {
            "event": {
              "name": "save_traveler",
              "context": {
                "name": {
                  "path": "/traveler/name"
                },
                "email": {
                  "path": "/traveler/email"
                },
                "seat": {
                  "path": "/traveler/seat"
                }
              }
            }
          }
        },
        {
          "id": "root",
          "component": "Column",
          "children": [
            "title",
            "name",
            "email",
            "seat",
            "save"
          ],
          "align": "stretch"
        },
        {
          "id": "_inline_1",
          "component": "Text",
          "text": "Save traveller"
        }
      ]
    }
  }
]
```

**Changing one value on a surface that is already on screen. No components, no root — just the data. The host re-renders in place.**

```json
[
  {
    "version": "v0.9.1",
    "updateDataModel": {
      "surfaceId": "home",
      "path": "/",
      "value": {
        "home": {
          "budgetUsed": 1480,
          "budgetCaption": "$1,480 of $2,000"
        }
      }
    }
  }
]
```
