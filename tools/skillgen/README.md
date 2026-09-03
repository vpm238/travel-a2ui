# skillgen

Turns an A2UI component catalog into skills a model can use.

```bash
PYTHONPATH=src python3 -m skillgen build --all \
  --catalog ../../catalogs/a2ui-travel/catalog.json \
  --examples ../../catalogs/a2ui-travel/examples \
  --out ../../skills
```

From the repository root, `npm run generate` does the same thing, along with the
catalog and the compiled examples.

No dependencies. Python 3.10+.

## Why it is a port and not an import

The reference implementation of this lives in
[google/a2ui](https://github.com/google/a2ui)'s Python agent SDK. Importing it
would pull in the whole ADK dependency tree — fifty-odd packages — to read a JSON
file and print some signatures, on every CI run.

So `catalog.py` and the signature half of `formats/express.py` are ports. The
shortcut is only honest while the two agree, so `tests/test_sdk_parity.py` diffs
them character for character whenever the reference SDK happens to be installed,
and skips when it is not:

```bash
pip install a2ui-agent-sdk
python3 -m pytest tests/test_sdk_parity.py -q
```

A signature block that has quietly drifted teaches the model a component API that
no longer exists, and it will fail at compile time in front of a user rather than
in CI. That test is the thing standing between here and there.

## The API

The module surface mirrors how the generation rules are written, so the code
reads like the spec it implements:

```python
from skillgen import CatalogHelper, ExpressFormat, build_monolithic_skill

helper = CatalogHelper.from_path("catalogs/a2ui-travel/catalog.json")
fmt = ExpressFormat()

skill = build_monolithic_skill(
    format_rules=fmt.generate_base_rules(),
    catalog_instructions=fmt.generate_catalog_instructions(helper),
    examples=fmt.generate_examples(examples),
    description=helper.description,
    protocol_version="0.9.1",
    inference_format=fmt.id,
    catalogs=["a2ui-travel"],
    catalog_id=helper.catalog_id,
)
print(skill.render())
```

| Piece | What it does |
|---|---|
| `CatalogHelper` | Crawls a catalog's JSON Schema for components, functions, property order, required sets, enums and descriptions. |
| `ExpressFormat` / `DirectJsonFormat` | `generate_base_rules()`, `generate_catalog_instructions(helper)`, `generate_examples(...)` — one inference format each. |
| `build_monolithic_skill` / `build_core_skill` / `build_catalog_skill` | Assemble a `Skill` (frontmatter + body) in one of the two shapes. |
| `generate(GenerationRequest)` | The whole pipeline for one variant, written to disk. |

### Naming

`catalog_skill_name` implements the rule that a catalog skill is
`a2ui-{catalog}`, without doubling a prefix the catalog already has:

```python
catalog_skill_name("travel")       # → a2ui-travel
catalog_skill_name("a2ui-travel")  # → a2ui-travel
catalog_skill_name("basic", prefix="a2ui-catalog-")  # → a2ui-catalog-basic
```

## Adding a catalog

1. Write the catalog JSON (see `scripts/build_catalog.py` for how the travel one
   extends the upstream basic catalog).
2. Author examples as `.express` files beside it, with a leading `#` comment as
   the title.
3. Run the generator with `--catalog` and `--examples` pointing at them.

Nothing in `skillgen` knows anything about travel. The domain lives entirely in
the catalog's component descriptions and its `instructions` field — which is
where it should live, because that is the text the model actually reads.

## Tests

```bash
python3 -m pytest tests -q       # 28 tests, no dependencies beyond pytest
```

They check the things that would otherwise fail silently: that the frontmatter
parses under a strict reader, that the model-facing fields leak no
implementation detail, that the modular pair covers every component the monolith
does, that generation is deterministic, and that no skill ships a script.
