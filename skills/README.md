# Generated skills

Everything in this directory is generated from
`catalogs/a2ui-travel/catalog.json` by the A2UI SDK's `SkillGenerator`, driven
by [`scripts/build_skills.py`](../scripts/build_skills.py). Edit the catalog or
the generator, not these files — `npm run check` fails the build if they drift.

```bash
npm run generate      # rewrite them
npm run check         # fail if they are stale
```

**These are the generated skills, and they are not the whole contract.** They
say what components exist and how to emit them. What the agent does *when* —
which step comes next, how a route is shaped, which control a decision is asked
in — is authored markdown in [`prompts/`](../prompts), because it is judgement
rather than a catalog. Both halves reach the model in the same system prompt.

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

## The shape, and how it was chosen

| Directory | Skills | Shape |
|---|---|---|
| `express-modular/` | `a2ui-core` + `a2ui-travel` | The notation, which never varies, split from the catalog, which does. |

There were three. The same catalog was also generated as one Express skill and
as raw A2UI JSON with no compiler in the path, and keeping all three was the
point: the question of what Express buys you on a given model is answerable by
measurement rather than by argument.

So it was measured — [`tools/eval/skills.py`](../tools/eval/skills.py), four asks
(a form, a list to choose from, a schedule, a total), three samples each,
scored on whether anything compiled, whether it compiled without being sent
back, and whether the component the ask was about was actually on the surface:

| Variant | right | clean | drew |
|---|---|---|---|
| `express-modular` | 11/12 | 10/12 | 11/12 |
| `express-monolithic` | 10/12 | 9/12 | 10/12 |
| `direct-json-monolithic` | 3/12 | 3/12 | 3/12 |

Direct JSON drew nothing at all on three of the four asks, and was the slowest
of the three doing it. Five more samples on the two scenarios where the Express
shapes differed put modular ahead again, 10/10 against 9/10, with no scenario
where monolithic won — so there was nothing to split per scenario either.

Modular is also the shape that scales past one domain: an agent working on
travel loads `a2ui-core` + `a2ui-travel` and never pays for the charting
catalog. Adding a second domain adds one skill, not a second copy of the
grammar.

A generated sample of each retired shape is kept in
[`docs/skill-variants/`](../docs/skill-variants), and
`VARIANTS` in `scripts/build_skills.py` is one line: put a shape back and re-run
the evaluation whenever a new model makes the question live again.

**The directory carries the variant; the skill name stays clean** — a skill that
renames itself to say which generator produced it is a skill whose description
is doing the wrong job.

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
