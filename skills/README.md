# Generated skills

Everything in this directory is generated from
`catalogs/a2ui-travel/catalog.json` by [`tools/skillgen`](../tools/skillgen).
Edit the catalog or the generator, not these files —
`npm run check` fails the build if they drift.

```bash
npm run generate      # rewrite them
npm run check         # fail if they are stale
```

## The naming principle

A skill's `name` and `description` are what an agent sees during discovery, and
all it sees before deciding whether to load the thing. So they describe a
**capability**, never an implementation:

```yaml
name: a2ui-travel
description: "Plans trips as interactive UI: flight and hotel options,
  day-by-day itineraries, price breakdowns, and trip dashboards."
metadata:
  protocol_version: "0.9.1"
  inference_format: express
  catalog: a2ui-travel
  catalog_id: https://travel-a2ui.dev/catalogs/a2ui-travel/catalog.json
  requires:
    - a2ui-core
```

Which inference format the SDK compiles, which protocol version is on the wire,
which schema file the signatures came from: none of that helps a model route a
request, and all of it crowds out the words that do. It is not thrown away — it
goes in `metadata`, where SDKs, platform indexers and a human debugging a bad
render can read it, and where it costs the model nothing.

A test enforces this: `description` may not contain "express", "json", "schema",
"sdk", "catalog.json" or a version number.

## The variants

| Directory | Skills | Shape |
|---|---|---|
| `express-monolithic/` | `a2ui` | Everything in one skill: format rules, the whole catalog, the examples. |
| `express-modular/` | `a2ui-core` + `a2ui-travel` | The notation, which never varies, split from the catalog, which does. |
| `direct-json-monolithic/` | `a2ui` | The same UI emitted as raw A2UI JSON — no compiler in the path. |

The variants live in sibling directories rather than under different skill names,
so the monolithic Express `a2ui` and the monolithic JSON `a2ui` can both exist
without either renaming itself to say which it is. **The directory carries the
variant; the skill name stays clean.**

Modular is the shape that scales past one domain: an agent working on travel
loads `a2ui-core` + `a2ui-travel` and never pays for the charting catalog. Adding
a second domain adds one skill, not a second copy of the grammar.

`direct_json` exists to be measured against. Running the same evaluation on both
formats is how you find out what Express is actually buying you on a given model,
rather than assuming.

You can switch between all three in the running app, mid-conversation, from the
header.

## No scripts

These skills are instructions. Nothing here requires a runtime on the agent's
side, and a test asserts that each skill directory contains nothing but
`SKILL.md`.

## What is in one

An Express skill has three parts, in this order:

1. **The output contract** — the grammar, the sentinel tags, streaming rules, and
   what the host does with the result. Identical across catalogs, which is why
   the modular shape can hoist it into `a2ui-core`.
2. **The catalog** — every component and function as a positional signature,
   with descriptions, enums, and `(static)` markers on properties that cannot
   take a data binding. Generated from the schema, in declaration order, because
   in a positional notation **declaration order is the API**.
3. **Examples** — the authored `.express` files from
   `catalogs/a2ui-travel/examples/`, which are compiled in CI. An example that
   does not compile is worse than no example: it teaches a mistake, confidently.
