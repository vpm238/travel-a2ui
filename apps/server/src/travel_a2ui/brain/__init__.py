"""The brain: what the agent knows, and what it can do.

Everything in this package is about *the agent*, and nothing in it knows which
door a request arrived through. That split is the point of the whole project:

    one brain, four doors, two renderers.

What lives here:

  `skills`        the contract the model is given — the role, the flow, how a
                  journey is shaped, which control a decision is asked in, and
                  the A2UI skill generated from the catalog. Markdown in
                  `prompts/` and generated skills in `skills/`, assembled.
  `tools`         the functions the model may call. They return data, never UI.
  `trip`          the record a trip is kept in, and the facts derived from it.
  `controls`      which control a decision may be asked in, checked not asked.
  `express`       compiling the A2UI the model emits, as it streams.
  `surface`       the passes every surface goes through before it goes out.
  `surfaces`      the surfaces this app draws without a model.
  `skeleton`      the surface drawn before the data arrives.
  `host_actions`  presses the host answers itself, without waking the model.
  `contract`      a fingerprint of all of the above, for doors that instantiate
                  against it once and hold it open.
  `providers`     where travel data comes from.

What is deliberately *not* here: anything about HTTP, websockets, JSON-RPC,
sessions or streaming transports. Those are doors, and a brain that knows about
them is a brain you cannot put behind a second one.
"""
