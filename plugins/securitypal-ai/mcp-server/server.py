#!/usr/bin/env python3
"""MCP stdio server exposing SecurityPal AI as a single Claude Desktop tool.

Reuses ``securitypal_copilot_api.py`` (the same helper the Codex and Claude
Code skill drives via its CLI) as the single source of truth: it loads that
module directly and calls its ``build_parser()`` / ``dispatch()`` functions,
so this file has no request-building or JSON:API-parsing logic of its own.

Exposes exactly one tool, ``securitypal_ai``, that takes a ``command`` (one
of the CLI's subcommand names, pulled from ``build_parser()`` at import time
so the list can't drift from the CLI) and a generic ``args`` object mapped
onto that subcommand's CLI flags.

Credentials: ``SECURITYPAL_API_TOKEN`` / ``SECURITYPAL_API_BASE_URL`` are
read from the environment by the underlying module exactly as the CLI does.
Claude Desktop injects them from the extension's ``user_config`` (see
``manifest.json``) — this file never touches the token directly.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

TOOL_NAME = "securitypal_ai"


def _load_copilot_api() -> ModuleType:
    """Load securitypal_copilot_api.py: a vendored copy next to this file if
    the extension has been packaged (see the build script), otherwise the
    source copy under skills/ for local development."""
    here = Path(__file__).resolve().parent
    vendored = here / "securitypal_copilot_api.py"
    source = (
        here.parent / "skills" / "securitypal-ai" / "scripts" / "securitypal_copilot_api.py"
    )
    script_path = vendored if vendored.exists() else source
    spec = importlib.util.spec_from_file_location("securitypal_copilot_api", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load securitypal_copilot_api.py from {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["securitypal_copilot_api"] = module
    spec.loader.exec_module(module)
    return module


copilot = _load_copilot_api()


def _command_names() -> list[str]:
    """Pull the CLI's subcommand names straight from build_parser() so this
    tool's schema can never list a command the CLI doesn't have (or omit one
    it does)."""
    parser = copilot.build_parser()
    for action in parser._actions:  # noqa: SLF001 - argparse has no public API for this
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            return sorted(action.choices.keys())
    return []


def _dest_to_flag_map(command: str) -> dict[str, str]:
    """Map each of a subcommand's argparse dest names to its actual CLI flag
    string. Some flags don't follow a simple dest-with-hyphens pattern (e.g.
    ``--tag-id`` is singular but ``dest="tag_ids"`` because it's repeatable),
    so this reads the real mapping from the parser instead of guessing."""
    parser = copilot.build_parser()
    for action in parser._actions:  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            subparser = action.choices.get(command)
            if subparser is None:
                return {}
            return {
                act.dest: act.option_strings[-1]
                for act in subparser._actions  # noqa: SLF001
                if act.option_strings
            }
    return {}


def _args_to_argv(command: str, args: dict[str, Any]) -> list[str]:
    """Convert a generic {dest_name: value} object into CLI-style argv
    tokens, so build_parser().parse_args() can do all the validation,
    defaulting, and type coercion the CLI already relies on."""
    flag_by_dest = _dest_to_flag_map(command)
    argv: list[str] = []
    for key, value in args.items():
        flag = flag_by_dest.get(key)
        if flag is None:
            raise ValueError(
                f"Unknown argument '{key}' for command '{command}'. "
                f"Valid arguments: {', '.join(sorted(flag_by_dest)) or 'none'}."
            )
        if value is None:
            continue
        if isinstance(value, bool):
            if value:
                argv.append(flag)
            continue
        if isinstance(value, list):
            for item in value:
                argv.extend([flag, str(item)])
            continue
        argv.extend([flag, str(value)])
    return argv


def _tool_description() -> str:
    commands = ", ".join(_command_names())
    return (
        "Call any SecurityPal AI Knowledge Library command. Set `command` to "
        f"one of: {commands}.\n\n"
        "Set `args` to that command's flags, using the CLI's flag names "
        "without the leading `--`, as snake_case object keys — `--library-id "
        '123` becomes `{"library_id": 123}`, a repeatable flag like '
        '`--tag-id` becomes a JSON array (`{"tag_ids": ["abc", "def"]}`), and '
        'a boolean flag like `--include-tags` is `{"include_tags": true}` or '
        "omitted entirely if false. Omit `args` (or pass `{}`) for commands "
        "that take no flags, e.g. `check-auth` or `me`.\n\n"
        "Run `check-auth` first if you're unsure whether credentials are "
        "configured correctly."
    )


def _input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": _command_names(),
                "description": "Which SecurityPal AI command to run.",
            },
            "args": {
                "type": "object",
                "description": "Flags for the given command (see the tool description for the mapping).",
                "additionalProperties": True,
            },
        },
        "required": ["command"],
    }


server: Server = Server("securitypal-ai")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name=TOOL_NAME,
            description=_tool_description(),
            inputSchema=_input_schema(),
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    if name != TOOL_NAME:
        raise ValueError(f"Unknown tool: {name}")

    command = str(arguments.get("command"))
    tool_args = arguments.get("args") or {}

    try:
        argv = [command, *_args_to_argv(command, tool_args)]
        parsed_args = copilot.build_parser().parse_args(argv)
        result = copilot.dispatch(parsed_args.command, parsed_args)
    except ValueError as exc:
        return [types.TextContent(type="text", text=json.dumps({"error": str(exc)}))]
    except SystemExit as exc:
        return [
            types.TextContent(
                type="text",
                text=json.dumps({"error": str(exc.code) if exc.code else str(exc)}),
            )
        ]
    except copilot.ApiRequestError as exc:
        return [types.TextContent(type="text", text=json.dumps({"error": exc.as_dict()}))]

    return [
        types.TextContent(
            type="text",
            text=json.dumps(result, indent=2, sort_keys=True, default=str),
        )
    ]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
