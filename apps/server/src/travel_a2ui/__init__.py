"""The travel agent, server-side.

Everything the traveller sees is composed here and sent as A2UI. The React app
in front is a renderer and nothing else: it holds no travel logic, no catalog
knowledge and no opinion about what a trip is — which is what makes the same
surfaces draw in an MCP host, or a Flutter app, or a voice call.

Python because the A2UI agent SDK is Python. `agent_sdks/` upstream contains
exactly one language, and a TypeScript port of it was 2,943 lines kept in step
with a reference implementation by a parity suite. That port now only has to
exist for as long as this server does not.

Two packages, and the split is the architecture:

  `brain`   what the agent knows and what it can do — skills, tools, the trip
            record, the surface passes. Knows nothing about transports.
  `doors`   the same brain reachable four ways: the Interactions API, the Live
            API, MCP, and the HTTP app that mounts them.

The renderers are outside this package entirely — `renderers/react` and
`renderers/flutter` — and neither holds any travel logic. They
draw A2UI, send actions back, and wait for the next A2UI.
"""

import pathlib

__all__ = ["ROOT", "__version__"]

#: The project root, resolved once.
#:
#: Every module that reads `data/`, `prompts/`, `skills/` or `catalogs/` used to
#: count directories back from its own file — `parents[4]`, repeated nine times.
#: Splitting the package into `brain` and `doors` moved every one of those files
#: a level deeper and broke all nine at once, which is the argument for having
#: written it down in one place to begin with.
ROOT = pathlib.Path(__file__).resolve().parents[4]

# Said here, once, because the alternative is what CI actually printed:
# "10-inline-flight-options.express does not compile: FileNotFoundError:
# .../scratch/ci312/catalogs/a2ui-travel/catalog.json". Counting four
# directories up from this file reaches the repository when the package is read
# out of `apps/server/src` and lands somewhere inside the virtualenv when it has
# been copied into site-packages — so every data path goes with it, and the
# first thing that breaks is whichever module reads a file at import time.
#
# The image installs this with `-e` (see the Dockerfile) for exactly this
# reason, and so does CI. This turns the same mistake into a sentence saying so.
if not (ROOT / "catalogs" / "a2ui-travel").is_dir():
    raise ImportError(
        f"travel_a2ui resolved the project root to {ROOT}, which has no "
        "catalogs/a2ui-travel in it. This package reads catalogs, prompts, "
        "skills and data from the tree it sits in, so it has to be installed "
        "from source rather than copied into site-packages: "
        "`pip install -e ./apps/server`."
    )

__version__ = "0.1.0"
