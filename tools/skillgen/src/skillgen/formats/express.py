"""The A2UI Express inference format.

Express is a compact, Python-flavoured notation for describing a UI tree that a
host compiles into A2UI JSON envelopes. It exists because JSON is a bad thing to
ask a model to emit under a streaming deadline: it is roughly three times the
tokens, a truncated object is unparseable, and every nested component needs an
id the model has to invent and then remember.

Express is the opposite on all three counts — variables *are* the ids, a partial
program is still a program, and the compiler does the bookkeeping.

Signature generation here is a port of ``ExpressPromptGenerator`` from
google/a2ui, character-for-character: ``tests/test_sdk_parity.py`` diffs this
against the reference output when the SDK is installed.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ..catalog import CatalogHelper, allows_databinding, find_enum, is_component_id

FORMAT_ID = "express"

# The grammar contract. This is the single highest-leverage text in the project:
# it is what stands between the model and a compile error, on every turn.
BASE_RULES = """\
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

4. **Primitives.** Strings use `"…"` or `\"\"\"…\"\"\"`, with `\\n`, `\\t`, `\\\\`
   and `\\"` escapes; prefix with `r` for a raw string. Numbers are bare
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

12. **`(static only)` arguments take literals only.** They are marked in the
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
those envelopes yourself — write Express and let the compiler produce them.\
"""


class ExpressFormat:
    """Generates the Express half of a skill: rules, signatures, examples."""

    id = FORMAT_ID

    def generate_base_rules(self) -> str:
        """The format's core syntax specification, envelopes and streaming rules."""
        return BASE_RULES

    # -- signature generation (ported from ExpressPromptGenerator) ----------

    def generate_component_signatures(self, helper: CatalogHelper) -> str:
        signatures: list[str] = []
        for name in sorted(helper.component_properties.keys()):
            props = helper.get_component_properties(name)
            required = helper.get_component_required(name)
            description = helper.get_component_description(name)

            ordered_args: list[str] = []
            details: list[str] = []

            for prop in props:
                suffix = "" if prop in required else "?"
                schema = helper.get_property_schema(name, prop)
                label = f"{prop}{suffix}"

                if is_component_id(schema):
                    label += " (component ID)"
                elif not allows_databinding(schema):
                    label += " (static only)"
                ordered_args.append(label)

                prop_description = schema.get("description") if isinstance(schema, dict) else None
                enum_values = find_enum(schema)

                if prop_description or enum_values:
                    parts: list[str] = []
                    if prop_description:
                        parts.append(prop_description)
                    if enum_values:
                        rendered = ", ".join(f"'{value}'" for value in enum_values)
                        parts.append(f"Must be one of: {rendered}")
                    details.append(f"  - {prop}: {' '.join(parts)}")

                nested = _nested_key_lines(schema)
                if nested:
                    kind, lines = nested
                    if details and details[-1].startswith(f"  - {prop}:"):
                        details[-1] += f"\n    {kind}:\n" + "\n".join(lines)
                    else:
                        details.append(f"  - {prop}: {kind.replace(' keys', ' with keys')}:\n" + "\n".join(lines))

            signature = f"• {name}({', '.join(ordered_args)})"
            if description:
                signature += f"\n  - Description: {description.replace(chr(10), chr(10) + '    ')}"
            if details:
                signature += "\n" + "\n".join(details)
            signatures.append(signature)

        return "\n".join(signatures)

    def generate_function_signatures(self, helper: CatalogHelper) -> str:
        signatures: list[str] = []
        for name in sorted(helper.function_properties.keys()):
            props = helper.get_function_properties(name)
            required = helper.get_function_required(name)
            description = helper.get_function_description(name)

            schema = helper.functions.get(name, {})
            arg_properties = (
                schema.get("properties", {}).get("args", {}).get("properties", {})
                if isinstance(schema, dict)
                else {}
            )

            ordered_args: list[str] = []
            details: list[str] = []
            for prop in props:
                suffix = "" if prop in required else "?"
                ordered_args.append(f"{prop}{suffix}")
                prop_schema = arg_properties.get(prop, {})
                prop_description = (
                    prop_schema.get("description") if isinstance(prop_schema, dict) else None
                )
                if prop_description:
                    details.append(f"  - {prop}: {prop_description}")

            signature = f"• {name}({', '.join(ordered_args)})"
            if description:
                signature += f"\n  - Description: {description.replace(chr(10), chr(10) + '    ')}"
            if details:
                signature += "\n" + "\n".join(details)
            signatures.append(signature)

        return "\n".join(signatures)

    def generate_catalog_instructions(self, helper: CatalogHelper) -> str:
        """The component and function signature block for one catalog."""
        components = self.generate_component_signatures(helper)
        functions = self.generate_function_signatures(helper)

        block = (
            "## Positional Component Signatures\n\n"
            "Use these exact positional signatures to instantiate components. "
            "Do not output property keys:\n"
            f"{components}\n\n"
            "## Positional Function Signatures\n\n"
            "Use these exact positional signatures to instantiate check rules or "
            f"logic functions:\n{functions}"
        )

        instructions = helper.instructions
        if instructions:
            block += f"\n\n## Catalog Instructions\n\n{instructions}"
        return block

    def generate_examples(self, examples: list[tuple[str, str]]) -> str:
        """Renders authored Express examples as fenced, sentinel-wrapped blocks.

        Each example arrives as ``(title, source)``. The leading ``#`` comment
        lines of the source are the title and are stripped from the body, so the
        example reads as a labelled sample rather than a commented one.
        """
        if not examples:
            return ""
        blocks: list[str] = []
        for title, source in examples:
            blocks.append(f"**{title}**\n\n```\n<a2ui>\n{source.strip()}\n</a2ui>\n```")
        return "## Examples\n\n" + "\n\n".join(blocks)


def _nested_key_lines(schema: Any) -> Optional[tuple[str, list[str]]]:
    """Describes the keys of an object property, or of an array's item objects."""
    if not isinstance(schema, dict):
        return None

    if schema.get("type") == "object" and isinstance(schema.get("properties"), dict):
        return "Map keys", _key_lines(schema["properties"])

    if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        items = schema["items"]
        if items.get("type") == "object" and isinstance(items.get("properties"), dict):
            return "List of maps keys", _key_lines(items["properties"])

    return None


def _key_lines(properties: dict[str, Any]) -> list[str]:
    lines = []
    for key, value in properties.items():
        description = value.get("description", "") if isinstance(value, dict) else ""
        lines.append(f"    * {key}{f' - {description}' if description else ''}")
    return lines


TITLE_COMMENT = re.compile(r"^\s*#\s?(.*)$")


def split_example(source: str) -> tuple[str, str]:
    """Splits leading ``#`` comment lines off an example as its title."""
    lines = source.splitlines()
    title_lines: list[str] = []
    index = 0
    while index < len(lines):
        match = TITLE_COMMENT.match(lines[index])
        if not match:
            break
        title_lines.append(match.group(1).strip())
        index += 1
    title = " ".join(part for part in title_lines if part).strip()
    body = "\n".join(lines[index:]).strip()
    return title or "Example", body
