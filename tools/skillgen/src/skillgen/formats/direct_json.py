"""The `direct_json` inference format.

The model emits A2UI wire messages itself, with no intermediate notation and no
compiler in the path. It costs roughly three times the tokens of Express and
gives up incremental rendering — a truncated JSON object is not a partial UI,
it is a parse error — so Express is the default.

It earns its place in two situations, both real:

- **A host with no compiler.** An MCP server or a third-party agent runtime that
  can forward JSON but cannot run the Express compiler needs the model to
  produce the final shape directly.
- **Measuring the compiler's value.** Running the same evaluation against both
  formats is how you find out what Express is actually buying you on a given
  model, rather than assuming.

Same catalog, same components, same examples — only the wire form differs. That
is the point of keeping both generated from one source.
"""

from __future__ import annotations

import json
from typing import Any

from ..catalog import CatalogHelper, allows_databinding, find_enum, is_component_id

FORMAT_ID = "direct_json"

BASE_RULES = """\
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
7. Properties marked `(static only)` below take literal values only — never a
   `{"path": …}` binding.

## Emitting

Emit the array in one piece and close the block with `</a2ui>`. Unlike the
Express format, a partial JSON array cannot be rendered, so do not narrate
between messages.\
"""


class DirectJsonFormat:
    """Generates the JSON half of a skill: envelope rules, catalog, examples."""

    id = FORMAT_ID

    def generate_base_rules(self) -> str:
        return BASE_RULES

    def generate_catalog_instructions(self, helper: CatalogHelper) -> str:
        lines: list[str] = [
            "## Components",
            "",
            "Each entry lists the component's properties. `!` marks a required "
            "property, `(static only)` one that cannot take a data binding, and "
            "`(component ID)` one that refers to another component by id.",
            "",
        ]

        for name in sorted(helper.component_properties.keys()):
            required = set(helper.get_component_required(name))
            rendered: list[str] = []
            for prop in helper.get_component_properties(name):
                schema = helper.get_property_schema(name, prop)
                label = f"{prop}{'!' if prop in required else ''}"
                if is_component_id(schema):
                    label += " (component ID)"
                elif not allows_databinding(schema):
                    label += " (static only)"
                enum_values = find_enum(schema)
                if enum_values:
                    label += " = " + "|".join(str(value) for value in enum_values)
                rendered.append(label)

            lines.append(f"• {name}: {', '.join(rendered)}")
            description = helper.get_component_description(name)
            if description:
                lines.append(f"  - {description}")

        lines.extend(["", "## Functions", "", "Used in `checks` conditions and dynamic values.", ""])
        for name in sorted(helper.function_properties.keys()):
            required = set(helper.get_function_required(name))
            rendered = [
                f"{prop}{'!' if prop in required else ''}"
                for prop in helper.get_function_properties(name)
            ]
            lines.append(f"• {name}({', '.join(rendered)})")
            description = helper.get_function_description(name)
            if description:
                lines.append(f"  - {description}")

        block = "\n".join(lines)
        if helper.instructions:
            block += f"\n\n## Catalog Instructions\n\n{helper.instructions}"
        return block

    def generate_examples(self, examples: list[tuple[str, Any]]) -> str:
        if not examples:
            return ""
        blocks: list[str] = []
        for title, messages in examples:
            rendered = json.dumps(messages, indent=2, ensure_ascii=False)
            blocks.append(f"**{title}**\n\n```json\n{rendered}\n```")
        return "## Examples\n\n" + "\n\n".join(blocks)
