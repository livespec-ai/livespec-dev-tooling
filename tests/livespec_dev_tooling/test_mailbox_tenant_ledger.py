"""The runnable mailbox entry binds its library contract to a tenant connection."""

from __future__ import annotations

import json
import subprocess
from io import StringIO
from pathlib import Path

import pytest

from livespec_dev_tooling import mailbox, mailbox_entry


class _Tenant:
    """A stand-in Beads tenant that records the adapter's raw-SQL requests."""

    def __init__(self, *, refuse_insert: bool = False) -> None:
        self.refuse_insert = refuse_insert
        self.sql: list[str] = []
        self.records: list[dict[str, object]] = [
            {
                "id": "mail-old",
                "from": "sender-a",
                "to": "recipient",
                "urgency": "urgent",
                "body": "first",
                "sent_at": "2026-11-22T06:00:00Z",
                "read_at": None,
                "read_by": None,
            },
            {
                "id": "mail-other",
                "from": "sender-b",
                "to": "other-seat",
                "urgency": "normal",
                "body": "private",
                "sent_at": "2026-11-22T05:00:00Z",
                "read_at": None,
                "read_by": None,
            },
        ]

    def execute(self, *, sql: str) -> object:
        self.sql.append(sql)
        if sql.startswith("CREATE TABLE"):
            return {"status": "ok"}
        if sql.startswith("INSERT"):
            return {"rows_affected": 0 if self.refuse_insert else 1}
        if sql.startswith("SELECT"):
            return [
                record
                for record in self.records
                if record["to"] == "recipient" and record["read_at"] is None
            ]
        if sql.startswith("UPDATE"):
            record = self.records[0]
            if record["read_at"] is not None:
                return {"rows_affected": 0}
            record["read_at"] = "2026-11-22T07:00:00Z"
            record["read_by"] = "recipient"
            return {"rows_affected": 1}
        raise AssertionError(sql)


def _run(*, tenant: _Tenant, argv: tuple[str, ...]) -> tuple[int, StringIO]:
    stdout = StringIO()
    return (
        mailbox_entry.main(
            argv=argv,
            connection=tenant,
            environ={"LIVESPEC_SEAT_NAME": "coordinator"},
            now=lambda: "2026-11-22T07:00:00Z",
            stdout=stdout,
        ),
        stdout,
    )


def test_send_writes_one_tenant_record_and_prints_its_id() -> None:
    """The entry performs its complete record write through the stand-in tenant."""
    tenant = _Tenant()
    status, stdout = _run(
        tenant=tenant,
        argv=("send", "--to", "recipient", "--urgency", "normal", "hold", "the", "roll"),
    )

    assert status == 0
    assert stdout.getvalue().strip()
    insert = next(sql for sql in tenant.sql if sql.startswith("INSERT"))
    for value in ("coordinator", "recipient", "normal", "hold the roll", "2026-11-22T07:00:00Z"):
        assert value in insert
    assert "read_at, read_by)" in insert


def test_refused_tenant_write_prints_no_record_id() -> None:
    """An unsuccessful insert cannot look like a sent mailbox message."""
    status, stdout = _run(
        tenant=_Tenant(refuse_insert=True),
        argv=("send", "--to", "recipient", "--urgency", "normal", "hold"),
    )

    assert status != 0
    assert stdout.getvalue() == ""


def test_read_delivers_only_the_recipient_messages_once() -> None:
    """The adapter asks the tenant for one seat and stamps the returned row."""
    tenant = _Tenant()
    status, stdout = _run(tenant=tenant, argv=("read", "--me", "recipient"))

    assert status == 0
    assert [json.loads(line) for line in stdout.getvalue().splitlines()] == [
        {
            "body": "first",
            "from": "sender-a",
            "id": "mail-old",
            "read_at": "2026-11-22T07:00:00Z",
            "read_by": "recipient",
            "sent_at": "2026-11-22T06:00:00Z",
            "to": "recipient",
            "urgency": "urgent",
        }
    ]
    assert "`to` = 'recipient'" in next(sql for sql in tenant.sql if sql.startswith("SELECT"))

    status, stdout = _run(tenant=tenant, argv=("read", "--me", "recipient"))
    assert status == 0
    assert stdout.getvalue() == ""


def test_credentialed_beads_connection_runs_sql_and_names_refusals(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The production connection uses the wrapper and never accepts a bad reply."""
    calls: list[tuple[object, object]] = []

    def completed(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=[], returncode=0, stdout='[{"id": "mail-1"}]')

    monkeypatch.setattr(mailbox_entry.subprocess, "run", completed)
    connection = mailbox_entry.BeadsTenantConnection(repo=tmp_path)

    assert connection.execute(sql="SELECT 1") == [{"id": "mail-1"}]
    assert calls == [
        (
            (
                [
                    "/usr/local/bin/with-livespec-env.sh",
                    "--",
                    "bd",
                    "-C",
                    str(tmp_path),
                    "sql",
                    "--json",
                    "SELECT 1",
                ],
            ),
            {"check": False, "capture_output": True, "text": True},
        )
    ]

    for response in (
        subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="refused"),
        subprocess.CompletedProcess(args=[], returncode=0, stdout="not json", stderr=""),
    ):

        def returns_response(
            *_args: object,
            response: subprocess.CompletedProcess[str] = response,
            **_kwargs: object,
        ) -> subprocess.CompletedProcess[str]:
            return response

        monkeypatch.setattr(
            mailbox_entry.subprocess,
            "run",
            returns_response,
        )
        with pytest.raises(mailbox.LedgerRefusalError):
            _ = connection.execute(sql="SELECT 1")


def test_connection_and_adapter_refusals_are_not_silently_accepted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Unavailable tenants and malformed adapter replies stay on the refusal rail."""
    connection = mailbox_entry.BeadsTenantConnection(repo=tmp_path)

    def unavailable(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError("wrapper absent")

    monkeypatch.setattr(mailbox_entry.subprocess, "run", unavailable)
    with pytest.raises(mailbox.LedgerRefusalError):
        _ = connection.execute(sql="SELECT 1")

    class BrokenTenant:
        def execute(self, *, sql: str) -> object:
            if sql.startswith("CREATE TABLE"):
                return {"status": "ok"}
            if sql.startswith("SELECT"):
                return {"not": "a list"}
            if sql.startswith("UPDATE"):
                return {"rows_affected": 0}
            return []

    ledger = mailbox_entry.BeadsMailboxLedger(connection=BrokenTenant(), new_id=lambda: "mail-1")
    with pytest.raises(mailbox.LedgerRefusalError):
        _ = ledger.unread_for(seat="recipient")
    with pytest.raises(mailbox.LedgerRefusalError):
        ledger.mark_read(record_id="mail-1", read_at="now", read_by="recipient")
    with pytest.raises(mailbox.LedgerRefusalError):
        _ = ledger.append(record={})


def test_adapter_rejects_bad_rows_and_preserves_connection_refusals() -> None:
    """Every non-record reply and connection failure is a mailbox refusal, not an empty read."""

    class BadReplyTenant:
        def execute(self, *, sql: str) -> object:
            if sql.startswith("CREATE TABLE"):
                return {"status": "ok"}
            if sql.startswith("SELECT"):
                return ["not a record"]
            return []

    bad_reply = mailbox_entry.BeadsMailboxLedger(
        connection=BadReplyTenant(), new_id=lambda: "mail-1"
    )
    with pytest.raises(mailbox.LedgerRefusalError):
        _ = bad_reply.unread_for(seat="recipient")
    with pytest.raises(mailbox.LedgerRefusalError):
        _ = bad_reply.append(
            record={
                "from": "sender",
                "to": "recipient",
                "urgency": "normal",
                "body": "body",
                "sent_at": "now",
            }
        )

    class RefusingTenant:
        def execute(self, *, sql: str) -> object:
            if sql.startswith("CREATE TABLE"):
                return {"status": "ok"}
            raise mailbox.LedgerRefusalError("refused")

    class UnavailableTenant:
        def execute(self, *, sql: str) -> object:
            if sql.startswith("CREATE TABLE"):
                return {"status": "ok"}
            raise OSError("unreachable")

    for tenant in (RefusingTenant(), UnavailableTenant()):
        ledger = mailbox_entry.BeadsMailboxLedger(connection=tenant)
        with pytest.raises(mailbox.LedgerRefusalError):
            _ = ledger.unread_for(seat="recipient")


def test_entry_requires_a_sender_seat_and_uses_utc_clock() -> None:
    """A runnable command cannot create an anonymous mailbox record."""
    assert mailbox_entry.main(argv=(), connection=_Tenant(), environ={}, stdout=StringIO()) == 2
    assert mailbox_entry._now().endswith("Z")  # noqa: SLF001 -- entry clock contract.
