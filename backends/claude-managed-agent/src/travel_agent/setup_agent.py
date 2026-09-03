"""Provisions the managed agent. Run once, not per request.

An agent is a persisted, versioned object: sessions pin to a version, so
changing the prompt is an *update* that bumps the version rather than a new
agent. Creating one per run would orphan the old ones, pay the create latency on
every conversation, and throw away the versioning that is the reason agents are
separate objects in the first place.

    python -m travel_agent.setup_agent --mcp-url https://your.workers.dev/mcp
    python -m travel_agent.setup_agent --update          # push a prompt change
"""

from __future__ import annotations

import argparse
import datetime
import sys

from .config import (
    AGENT_NAME,
    ENVIRONMENT_NAME,
    ROLE,
    SKILL_FILES,
    STATE_FILE,
    AgentState,
    load_skill,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="travel_agent.setup_agent", description=__doc__)
    parser.add_argument(
        "--mcp-url",
        help="Public URL of this project's MCP endpoint, e.g. "
        "https://travel-a2ui.<subdomain>.workers.dev/mcp. Anthropic calls it, so it "
        "has to be reachable from the internet — deploy the Worker first.",
    )
    parser.add_argument("--model", default="claude-opus-5")
    parser.add_argument("--skill", default="express-monolithic", choices=sorted(SKILL_FILES))
    parser.add_argument(
        "--compile-service",
        help="Base URL of a compile service, used when the installed a2ui SDK is "
        "too old to compile the current Express grammar. Usually the same origin "
        "as --mcp-url, without the /mcp.",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Update the existing agent in place, creating a new version.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        import anthropic
    except ImportError:
        print("The Anthropic SDK is not installed: pip install -e '.[dev]'", file=sys.stderr)
        return 1

    existing = AgentState.load()

    if args.update and existing is None:
        print(f"No {STATE_FILE} — run without --update first.", file=sys.stderr)
        return 1
    if not args.update and not args.mcp_url:
        print(
            "An MCP URL is required:\n"
            "  --mcp-url https://<your-worker>.workers.dev/mcp\n\n"
            "That is the endpoint this agent calls for travel data and A2UI "
            "surfaces. Deploy the Worker first (npm run deploy), then pass its "
            "/mcp URL here.",
            file=sys.stderr,
        )
        return 1

    client = anthropic.Anthropic()
    system = f"{ROLE}\n\n---\n\n{load_skill(args.skill)}"
    mcp_url = args.mcp_url or (existing.mcp_url if existing else "")

    # The sandbox toolset (bash, file operations) is deliberately absent: this
    # agent has no reason to run code, and a tool an agent cannot reach is a
    # tool it cannot misuse. Everything it needs comes from the MCP server.
    tools = [{"type": "mcp_toolset", "mcp_server_name": "travel-a2ui"}]
    mcp_servers = [{"type": "url", "name": "travel-a2ui", "url": mcp_url}]

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if args.update:
        assert existing is not None
        agent = client.beta.agents.update(
            existing.agent_id,
            model=args.model,
            system=system,
            mcp_servers=mcp_servers,
            tools=tools,
        )
        state = AgentState(
            agent_id=existing.agent_id,
            agent_version=agent.version,
            environment_id=existing.environment_id,
            mcp_url=mcp_url,
            skill_variant=args.skill,
            compile_service=args.compile_service or existing.compile_service,
            created_at=now,
        )
        state.save()
        print(f"Updated {state.agent_id} to version {state.agent_version}.")
        return 0

    print(f'Creating environment "{ENVIRONMENT_NAME}"…')
    environment = client.beta.environments.create(
        name=ENVIRONMENT_NAME,
        config={"type": "cloud", "networking": {"type": "unrestricted"}},
    )

    print(f'Creating agent "{AGENT_NAME}" on {args.model}…')
    agent = client.beta.agents.create(
        name=AGENT_NAME,
        model=args.model,
        system=system,
        mcp_servers=mcp_servers,
        tools=tools,
    )

    service = args.compile_service or mcp_url.removesuffix("/mcp") or None
    state = AgentState(
        agent_id=agent.id,
        agent_version=agent.version,
        environment_id=environment.id,
        mcp_url=mcp_url,
        skill_variant=args.skill,
        compile_service=service,
        created_at=now,
    )
    state.save()

    print(f"\nAgent           {state.agent_id} (version {state.agent_version})")
    print(f"Environment     {state.environment_id}")
    print(f"MCP server      {state.mcp_url}")
    print(f"Compile service {state.compile_service or '(the installed SDK)'}")
    print(f"Skill           {state.skill_variant} ({len(load_skill(args.skill)):,} chars)")
    print(f"\nWritten to {STATE_FILE}.\nStart the backend with:  python -m travel_agent.server")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
