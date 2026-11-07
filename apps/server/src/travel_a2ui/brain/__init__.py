"""The brain: what the agent knows, and what it can do.

Everything in this package is about *the agent*, and nothing in it knows which
door a request arrived through. That split is the point of the whole project:

    one brain, two doors, two renderers.

What lives here:

  `catalog`       the travel catalog, and the A2UI SDK processor configured
                  over it: the prompt snippet, the parser, the examples.
  `macros`        one-line components the model writes, expanded by the SDK's
                  `MacroExpander` into templates over host data.
  `ui`            reading the model's output through the processor, and the
                  mirror of the renderer every outbound message is checked
                  against.
  `data`          the data the host publishes for surfaces to bind.
  `inbound`       what a renderer sends back, read as A2UI v1.0.
  `skills`        the system prompt: `prompts/*.md` and the processor's snippet.
  `controls`      whether a surface can be answered as drawn, told to the model.
  `presses`       what a press settles, recorded before the model hears of it.
  `tools`         the functions the model may call. They return data, never UI.
  `trip`          the record a trip is kept in, and the facts derived from it.
  `host_actions`  presses the host answers itself, without waking the model.
  `providers`     where travel data comes from.

What is deliberately *not* here: anything about HTTP, websockets, sessions or
streaming transports. Those are doors, and a brain that knows about
them is a brain you cannot put behind a second one.
"""
