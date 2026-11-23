"""A durable, ledger-backed mailbox for cross-machine agent seats.

The command deliberately knows nothing about panes or host-local state.  Its
ledger dependency is injected so the harness hook, the urgent-message watcher,
and tests all exercise the same send/read behaviour against their own ledger
connection.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, TextIO

__all__: list[str] = ["LedgerRefusalError", "MailboxLedger", "main"]

_USAGE = "usage: mailbox send --to <seat> --urgency <normal|urgent> <body> | read --me <seat>"
_VALID_URGENCIES = frozenset({"normal", "urgent"})
_SEND_ARGUMENTS_MINIMUM = 6
_READ_ARGUMENTS_COUNT = 3


class LedgerRefusalError(Exception):
    """A mailbox operation the tenant ledger explicitly declined."""


class MailboxLedger(Protocol):
    """The mailbox-specific portion of the shared ledger connection."""

    def append(self, *, record: dict[str, object]) -> str:
        """Persist a new message and return its durable ledger id."""
        ...

    def unread_for(self, *, seat: str) -> Sequence[Mapping[str, object]]:
        """Return mailbox entries that are presently unread for ``seat``."""
        ...

    def mark_read(self, *, record_id: str, read_at: str, read_by: str) -> None:
        """Durably stamp a delivered entry as read by its recipient."""
        ...


@dataclass(frozen=True, kw_only=True)
class _CommandContext:
    """The injected identity, clock, output and tenant connection for one call."""

    ledger: MailboxLedger
    sender: str
    now: Callable[[], str]
    stdout: TextIO


def _write(*, stream: TextIO, line: str) -> None:
    _ = stream.write(line + "\n")


def _send(
    *,
    destination: str,
    urgency: str,
    body: str,
    context: _CommandContext,
) -> int:
    if not destination or urgency not in _VALID_URGENCIES or not body:
        return 2
    record: dict[str, object] = {
        "from": context.sender,
        "to": destination,
        "urgency": urgency,
        "body": body,
        "sent_at": context.now(),
        "read_at": None,
        "read_by": None,
    }
    try:
        record_id = context.ledger.append(record=record)
    except LedgerRefusalError:
        return 1
    if not record_id:
        return 1
    _write(stream=context.stdout, line=record_id)
    return 0


def _read(
    *,
    seat: str,
    context: _CommandContext,
) -> int:
    if not seat:
        return 2
    try:
        unread = context.ledger.unread_for(seat=seat)
    except LedgerRefusalError:
        return 1
    entries = sorted(
        (entry for entry in unread if entry.get("to") == seat and entry.get("read_at") is None),
        key=lambda entry: str(entry.get("sent_at", "")),
    )
    delivered: list[dict[str, object]] = []
    try:
        for entry in entries:
            record_id = entry.get("id")
            if not isinstance(record_id, str) or not record_id:
                return 1
            read_at = context.now()
            context.ledger.mark_read(record_id=record_id, read_at=read_at, read_by=seat)
            delivered.append(
                {
                    "id": record_id,
                    "from": entry.get("from"),
                    "to": entry.get("to"),
                    "urgency": entry.get("urgency"),
                    "body": entry.get("body"),
                    "sent_at": entry.get("sent_at"),
                    "read_at": read_at,
                    "read_by": seat,
                }
            )
    except LedgerRefusalError:
        return 1
    for entry in delivered:
        _write(stream=context.stdout, line=json.dumps(entry, sort_keys=True))
    return 0


def main(
    *,
    argv: Sequence[str],
    ledger: MailboxLedger,
    sender: str,
    now: Callable[[], str],
    stdout: TextIO,
) -> int:
    """Run one send or read command using the caller's tenant-bound ledger."""
    arguments = list(argv)
    context = _CommandContext(ledger=ledger, sender=sender, now=now, stdout=stdout)
    if arguments[:1] == ["send"] and len(arguments) >= _SEND_ARGUMENTS_MINIMUM:
        if arguments[1:2] != ["--to"] or arguments[3:4] != ["--urgency"]:
            return 2
        return _send(
            destination=arguments[2],
            urgency=arguments[4],
            body=" ".join(arguments[5:]),
            context=context,
        )
    if arguments[:2] == ["read", "--me"] and len(arguments) == _READ_ARGUMENTS_COUNT:
        return _read(seat=arguments[2], context=context)
    return 2


if __name__ == "__main__":  # pragma: no cover - production injects its tenant connection.
    _ = sys.stderr.write(_USAGE + "\n")
    raise SystemExit(2)
