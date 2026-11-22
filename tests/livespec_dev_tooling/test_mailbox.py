"""The durable ledger mailbox command's send contract."""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable, Sequence
from io import StringIO
from typing import Protocol, cast


class _Ledger(Protocol):
    """The only ledger operation the send command needs."""

    def append(self, *, record: dict[str, object]) -> str:
        """Persist one mailbox record and return its durable id."""


class _MailboxCommand(Protocol):
    """The command boundary, with the ledger and clock supplied by its caller."""

    def main(
        self,
        *,
        argv: Sequence[str],
        ledger: _Ledger,
        sender: str,
        now: Callable[[], str],
        stdout: StringIO,
    ) -> int:
        """Run one mailbox command."""


class _FakeLedger:
    """A stand-in ledger that assigns one durable record id."""

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def append(self, *, record: dict[str, object]) -> str:
        self.records.append(record)
        return "mail-17"


def test_mailbox_send_writes_one_complete_record_and_prints_its_id() -> None:
    """A sender gets the id only after its complete record reaches the ledger."""
    spec = importlib.util.find_spec("livespec_dev_tooling.mailbox")
    assert spec is not None, "the committed mailbox command module must exist"
    mailbox = cast("_MailboxCommand", importlib.import_module(spec.name))
    ledger = _FakeLedger()
    stdout = StringIO()

    assert (
        mailbox.main(
            argv=("send", "--to", "ops-seat", "--urgency", "urgent", "stop the roll"),
            ledger=ledger,
            sender="coordinator",
            now=lambda: "2026-11-22T06:45:00Z",
            stdout=stdout,
        )
        == 0
    )

    assert ledger.records == [
        {
            "from": "coordinator",
            "to": "ops-seat",
            "urgency": "urgent",
            "body": "stop the roll",
            "sent_at": "2026-11-22T06:45:00Z",
            "read_at": None,
            "read_by": None,
        }
    ]
    assert stdout.getvalue() == "mail-17\n"
