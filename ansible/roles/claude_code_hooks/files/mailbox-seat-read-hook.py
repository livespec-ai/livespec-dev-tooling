#!/usr/bin/env python3
"""Inject unread durable-mailbox messages at Claude Code turn boundaries.

This host-installed hook has no dependency on the checkout that provisioned
it.  It discovers the launched seat from its tmux session, asks the durable
mailbox for messages addressed to that seat, and returns those messages only
through Claude Code's context-injection protocol.  Every operational failure
fails open: a seat must never wait on a ledger read to begin its next turn.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from typing import Final, cast

__all__: list[str] = ["main"]

_COMMAND_TIMEOUT_SECONDS: Final = 2
_HOOK_EVENT_NAME: Final = "UserPromptSubmit"


def _run(*, argv: Sequence[str]) -> subprocess.CompletedProcess[str] | None:
    """Run one bounded read-only helper command or return the fail-open case."""
    try:
        return subprocess.run(  # noqa: S603 -- fixed hook-owned argv.
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _seat_name() -> str | None:
    """Return the tmux session name under which this hook's seat was launched."""
    completed = _run(argv=("tmux", "display-message", "-p", "#S"))
    if completed is None or completed.returncode != 0:
        return None
    seat = completed.stdout.strip()
    return seat or None


def _unread_messages(*, seat: str) -> list[dict[str, str]]:
    """Read well-formed unread entries, treating every ledger error as empty."""
    completed = _run(argv=("mailbox", "read", "--me", seat))
    if completed is None or completed.returncode != 0:
        return []
    messages: list[dict[str, str]] = []
    for line in completed.stdout.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return []
        if not isinstance(record, dict):
            return []
        entry = cast("Mapping[str, object]", record)
        sender = entry.get("from")
        urgency = entry.get("urgency")
        body = entry.get("body")
        if not all(isinstance(value, str) and value for value in (sender, urgency, body)):
            return []
        messages.append({"from": sender, "urgency": urgency, "body": body})
    return messages


def _context(*, messages: Sequence[Mapping[str, str]]) -> str:
    """Render every delivered message as agent context, preserving its metadata."""
    return "\n\n".join(
        f"Mailbox message from {message['from']} (urgency: {message['urgency']}):\n"
        f"{message['body']}"
        for message in messages
    )


def main() -> int:
    """Return a context injection for unread mail, or silently fail open."""
    seat = _seat_name()
    if seat is None:
        return 0
    messages = _unread_messages(seat=seat)
    if not messages:
        return 0
    response = {
        "hookSpecificOutput": {
            "hookEventName": _HOOK_EVENT_NAME,
            "additionalContext": _context(messages=messages),
        }
    }
    _ = sys.stdout.write(f"{json.dumps(response)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
