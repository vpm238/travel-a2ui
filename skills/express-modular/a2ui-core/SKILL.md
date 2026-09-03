---
name: a2ui-core
description: Core rules for generating user interfaces. Load alongside a UI component skill whenever a response would be clearer as an interface than as text.
metadata:
  protocol_version: "0.9.1"
  inference_format: express
  companion_skills:
    - a2ui-travel
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
those envelopes yourself — write Express and let the compiler produce them.

## Component catalogs

This skill defines the notation, not the components. The components you may use come from a companion catalog skill (`a2ui-travel`). Load one alongside this skill; without it you have grammar and no vocabulary.
