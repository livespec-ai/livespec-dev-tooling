"""The durable ledger mailbox command's send, refusal and read-once delivery contracts."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from io import StringIO
from typing import cast

from livespec_dev_tooling import mailbox


class _FakeLedger:
    """An in-memory ledger that exposes the command's mailbox operations."""

    def __init__(
        self,
        *,
        append_result: object = "mail-sent",
        fail_read: bool = False,
        fail_stamp: bool = False,
        refuse_append: bool = False,
    ) -> None:
        self.append_result = append_result
        self.fail_read = fail_read
        self.fail_stamp = fail_stamp
        self.refuse_append = refuse_append
        self.records: list[dict[str, object]] = [
            {
                "id": "mail-newer",
                "from": "sender-b",
                "to": "ops-seat",
                "urgency": "normal",
                "body": "newer",
                "sent_at": "2026-11-22T07:01:00Z",
                "read_at": None,
                "read_by": None,
            },
            {
                "id": "mail-other-seat",
                "from": "sender-c",
                "to": "other-seat",
                "urgency": "urgent",
                "body": "private",
                "sent_at": "2026-11-22T06:59:00Z",
                "read_at": None,
                "read_by": None,
            },
            {
                "id": "mail-older",
                "from": "sender-a",
                "to": "ops-seat",
                "urgency": "urgent",
                "body": "older",
                "sent_at": "2026-11-22T07:00:00Z",
                "read_at": None,
                "read_by": None,
            },
        ]

    def append(self, *, record: dict[str, object]) -> str:
        if self.refuse_append:
            raise mailbox.LedgerRefusalError("ledger refused write")
        self.records.append(record)
        return cast("str", self.append_result)

    def unread_for(self, *, seat: str) -> Sequence[Mapping[str, object]]:
        _ = seat
        if self.fail_read:
            raise mailbox.LedgerRefusalError("ledger unavailable")
        return tuple(self.records)

    def mark_read(self, *, record_id: str, read_at: str, read_by: str) -> None:
        if self.fail_stamp:
            raise mailbox.LedgerRefusalError("ledger refused read stamp")
        for record in self.records:
            if record.get("id") == record_id:
                record["read_at"] = read_at
                record["read_by"] = read_by
                return
        raise AssertionError("unknown record id")


def _run(
    *, ledger: _FakeLedger, argv: Sequence[str], now: Callable[[], str]
) -> tuple[int, StringIO]:
    stdout = StringIO()
    status = mailbox.main(
        argv=argv,
        ledger=ledger,
        sender="coordinator",
        now=now,
        stdout=stdout,
    )
    return status, stdout


def test_a_refused_send_prints_no_record_id() -> None:
    """The sender gets no success-shaped answer from a rejected ledger write."""
    status, stdout = _run(
        ledger=_FakeLedger(refuse_append=True),
        argv=("send", "--to", "ops-seat", "--urgency", "normal", "hold"),
        now=lambda: "2026-11-22T07:02:00Z",
    )

    assert status != 0
    assert stdout.getvalue() == ""


def test_read_returns_only_the_named_seat_messages_once_in_sent_order() -> None:
    """A read stamps the selected messages, so an immediate second read is empty."""
    ledger = _FakeLedger()
    status, stdout = _run(
        ledger=ledger,
        argv=("read", "--me", "ops-seat"),
        now=lambda: "2026-11-22T07:03:00Z",
    )

    assert status == 0
    assert [json.loads(line) for line in stdout.getvalue().splitlines()] == [
        {
            "body": "older",
            "from": "sender-a",
            "id": "mail-older",
            "read_at": "2026-11-22T07:03:00Z",
            "read_by": "ops-seat",
            "sent_at": "2026-11-22T07:00:00Z",
            "to": "ops-seat",
            "urgency": "urgent",
        },
        {
            "body": "newer",
            "from": "sender-b",
            "id": "mail-newer",
            "read_at": "2026-11-22T07:03:00Z",
            "read_by": "ops-seat",
            "sent_at": "2026-11-22T07:01:00Z",
            "to": "ops-seat",
            "urgency": "normal",
        },
    ]
    assert ledger.records[1]["read_at"] is None
    assert ledger.records[1]["read_by"] is None

    status, stdout = _run(
        ledger=ledger,
        argv=("read", "--me", "ops-seat"),
        now=lambda: "2026-11-22T07:04:00Z",
    )

    assert status == 0
    assert stdout.getvalue() == ""


def test_invalid_send_and_read_requests_do_not_write_or_print() -> None:
    """Malformed command lines fail before any ledger effect is attempted."""
    ledger = _FakeLedger()
    for argv in (
        ("send", "--urgency", "normal", "--to", "ops-seat", "hold"),
        ("send", "--to", "", "--urgency", "normal", "hold"),
        ("send", "--to", "ops-seat", "--urgency", "later", "hold"),
        ("send", "--to", "ops-seat", "--urgency", "normal", ""),
        ("read", "--me", ""),
        ("read",),
    ):
        status, stdout = _run(
            ledger=ledger,
            argv=argv,
            now=lambda: "2026-11-22T07:04:00Z",
        )
        assert status == 2
        assert stdout.getvalue() == ""


def test_an_unusable_ledger_answer_is_not_reported_as_a_sent_message() -> None:
    """A non-id append answer is a refusal, just like an exception from the ledger."""
    for append_result in ("", None):
        status, stdout = _run(
            ledger=_FakeLedger(append_result=append_result),
            argv=("send", "--to", "ops-seat", "--urgency", "normal", "hold"),
            now=lambda: "2026-11-22T07:04:00Z",
        )
        assert status == 1
        assert stdout.getvalue() == ""


def test_read_refusals_are_not_mistaken_for_an_empty_mailbox() -> None:
    """Neither an unread query failure nor an unstamped entry is returned."""
    for ledger in (
        _FakeLedger(fail_read=True),
        _FakeLedger(fail_stamp=True),
        _FakeLedger(),
    ):
        if not ledger.fail_read and not ledger.fail_stamp:
            ledger.records[0]["id"] = None
        status, stdout = _run(
            ledger=ledger,
            argv=("read", "--me", "ops-seat"),
            now=lambda: "2026-11-22T07:04:00Z",
        )
        assert status == 1
        assert stdout.getvalue() == ""


def test_mailbox_send_writes_one_complete_record_and_prints_its_id() -> None:
    """A sender gets the id only after its complete record reaches the ledger."""
    ledger = _FakeLedger(append_result="mail-17")
    stdout = StringIO()

    exit_code = mailbox.main(
        argv=("send", "--to", "ops-seat", "--urgency", "urgent", "stop the roll"),
        ledger=ledger,
        sender="coordinator",
        now=lambda: "2026-11-22T06:45:00Z",
        stdout=stdout,
    )

    assert exit_code == 0
    assert ledger.records[-1] == {
        "from": "coordinator",
        "to": "ops-seat",
        "urgency": "urgent",
        "body": "stop the roll",
        "sent_at": "2026-11-22T06:45:00Z",
        "read_at": None,
        "read_by": None,
    }
    assert stdout.getvalue() == "mail-17\n"
