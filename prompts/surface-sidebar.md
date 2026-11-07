## This surface: the panel — what is settled, and nothing else

A persistent panel beside the conversation showing the trip as it stands. It is
**read-only**: deciding happens in the conversation, and this is the record.

**Draw it with `Trip()`, once.** It binds `$/panel`, which the host keeps equal
to the record, so every later decision reaches it as data:

    <a2ui>
    surface("sidebar")
    root = Column([panel])
    panel = Trip("Your trip to Madrid")
    </a2ui>

Each hop shows its route, dates and party, and its fare and stay once chosen,
each with a Change button that sends `change` with `{what, hop}`. Once anything
is priced, update it to carry the money: `surface("sidebar", update=true)` and
`panel = Trip("Your trip to Madrid", true)`.

To compose it by hand instead, the same facts are bound data:

- `$/panel/hops` — one row per hop: `title`, `when`, and `flights` and `stays`
  as lists of none or one, so a template over them shows a card only once that
  decision is made.
- `$/plan/decisions` — every trip-wide decision, each with `key`, `label` and
  `value`; `$/plan/route` — one row per hop with `place`, `from`, `nights`,
  its own `decisions`, and `wants` (what it still needs).
- `$/money` — `total`, `budget`, `remaining`, `over` and `currency`, as numbers:
  bind them through `formatCurrency($/money/total, $/money/currency)`.

Rules for the panel:

- **No editors here.** No slider, date picker, counter, text field or checkbox:
  a control in a read-only record visibly does nothing.
- **The only button is Change**, and its only event is `change`, naming what it
  re-opens: `Event("change", {what: "flight", hop: 1})` or `{field: "startDate"}`.
- If nothing is decided yet, draw nothing here: an empty record says nothing.
- Target the surface id `sidebar`.
