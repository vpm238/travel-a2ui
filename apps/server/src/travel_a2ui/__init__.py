"""The travel agent, server-side.

Everything the traveller sees is composed here and sent as A2UI. The React app
in front is a renderer and nothing else: it holds no travel logic, no catalog
knowledge and no opinion about what a trip is — which is what makes the same
surfaces draw in an MCP host, or a Flutter app, or a voice call.

Python because the A2UI agent SDK is Python. `agent_sdks/` upstream contains
exactly one language, and a TypeScript port of it was 2,943 lines kept in step
with a reference implementation by a parity suite. That port now only has to
exist for as long as this server does not.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
