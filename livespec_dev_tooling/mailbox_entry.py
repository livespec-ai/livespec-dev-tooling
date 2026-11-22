"""Run the durable mailbox against this checkout's Beads tenant.

The entry deliberately reaches the tenant through ``bd sql`` under the fleet
credential wrapper.  The adapter's connection seam keeps the command's
ledger behaviour testable without a Dolt server while keeping the production
route on the configured Beads tenant.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, TextIO, cast

from livespec_dev_tooling import mailbox

__all__: list[str] = ["BeadsMailboxLedger", "BeadsTenantConnection", "main"]

_CREDENTIAL_WRAPPER = "/usr/local/bin/with-livespec-env.sh"
_SEAT_NAME_ENV = "LIVESPEC_SEAT_NAME"
_TABLE = "mailbox_messages"
_NON_JSON_REPLY = "bd sql returned non-JSON output"
_INSERT_REFUSED = "mailbox insert did not write one record"
_READ_REPLY_REFUSED = "mailbox read did not return records"
_STAMP_REFUSED = "mailbox read stamp did not update one record"
_MISSING_RECORD_FIELD = "mailbox record lacks a required field"


class TenantConnection(Protocol):
    """The raw-SQL portion of one credentialed Beads tenant connection."""

    def execute(self, *, sql: str) -> object:
        """Run one statement and return its JSON-decoded Beads reply."""
        ...


class BeadsTenantConnection:
    """Execute raw SQL against the checkout's configured Beads tenant."""

    def __init__(self, *, repo: Path) -> None:
        self._repo = repo

    def execute(self, *, sql: str) -> object:
        """Run ``bd sql`` through the credential wrapper or name the refusal."""
        command = [
            _CREDENTIAL_WRAPPER,
            "--",
            "bd",
            "-C",
            str(self._repo),
            "sql",
            "--json",
            sql,
        ]
        try:
            completed = subprocess.run(  # noqa: S603 -- fixed executable and adapter-built argv.
                command, check=False, capture_output=True, text=True
            )
        except OSError as error:
            raise mailbox.LedgerRefusalError(str(error)) from error
        if completed.returncode != 0:
            raise mailbox.LedgerRefusalError(completed.stderr.strip() or "bd sql refused")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise mailbox.LedgerRefusalError(_NON_JSON_REPLY) from error


class BeadsMailboxLedger:
    """The mailbox protocol backed by a table in the configured Beads tenant."""

    def __init__(
        self, *, connection: TenantConnection, new_id: Callable[[], str] | None = None
    ) -> None:
        self._connection = connection
        self._new_id = new_id or (lambda: uuid.uuid4().hex)
        self._schema_ready = False

    def append(self, *, record: dict[str, object]) -> str:
        """Insert one complete mailbox record and return its durable id."""
        self._ensure_schema()
        record_id = self._new_id()
        values = [
            record_id,
            _required_text(record=record, field="from"),
            _required_text(record=record, field="to"),
            _required_text(record=record, field="urgency"),
            _required_text(record=record, field="body"),
            _required_text(record=record, field="sent_at"),
        ]
        reply = self._execute(
            sql=_sql(
                "INSERT INTO ",
                _TABLE,
                " (id, `from`, `to`, urgency, body, sent_at, read_at, read_by) VALUES (",
                ", ".join(_quote(value=value) for value in values),
                ", NULL, NULL)",
            )
        )
        if _rows_affected(reply=reply) != 1:
            raise mailbox.LedgerRefusalError(_INSERT_REFUSED)
        return record_id

    def unread_for(self, *, seat: str) -> Sequence[Mapping[str, object]]:
        """Return unread records addressed to exactly ``seat`` from the tenant."""
        self._ensure_schema()
        reply = self._execute(
            sql=_sql(
                "SELECT id, `from`, `to`, urgency, body, sent_at, read_at, read_by FROM ",
                _TABLE,
                " WHERE `to` = ",
                _quote(value=seat),
                " AND read_at IS NULL ORDER BY sent_at ASC, id ASC",
            )
        )
        if not isinstance(reply, list):
            raise mailbox.LedgerRefusalError(_READ_REPLY_REFUSED)
        items = cast("list[object]", reply)
        if not all(isinstance(item, dict) for item in items):
            raise mailbox.LedgerRefusalError(_READ_REPLY_REFUSED)
        return tuple(cast("Mapping[str, object]", item) for item in items)

    def mark_read(self, *, record_id: str, read_at: str, read_by: str) -> None:
        """Atomically stamp the named unread record, refusing a duplicate delivery."""
        self._ensure_schema()
        reply = self._execute(
            sql=_sql(
                "UPDATE ",
                _TABLE,
                " SET read_at = ",
                _quote(value=read_at),
                ", read_by = ",
                _quote(value=read_by),
                " WHERE id = ",
                _quote(value=record_id),
                " AND `to` = ",
                _quote(value=read_by),
                " AND read_at IS NULL",
            )
        )
        if _rows_affected(reply=reply) != 1:
            raise mailbox.LedgerRefusalError(_STAMP_REFUSED)

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        _ = self._execute(
            sql=_sql(
                "CREATE TABLE IF NOT EXISTS ",
                _TABLE,
                " (id VARCHAR(32) PRIMARY KEY, `from` TEXT NOT NULL, `to` TEXT NOT NULL, ",
                "urgency VARCHAR(16) NOT NULL, body TEXT NOT NULL, sent_at VARCHAR(32) NOT NULL, ",
                "read_at VARCHAR(32) NULL, read_by TEXT NULL)",
            )
        )
        self._schema_ready = True

    def _execute(self, *, sql: str) -> object:
        try:
            return self._connection.execute(sql=sql)
        except mailbox.LedgerRefusalError:
            raise
        except (OSError, ValueError, TypeError) as error:
            raise mailbox.LedgerRefusalError(str(error)) from error


def _quote(*, value: str) -> str:
    """Quote one text value for the fixed SQL shapes in this adapter."""
    return "'" + value.replace("\\", "\\\\").replace("'", "''").replace("\x00", "\\0") + "'"


def _sql(*parts: str) -> str:
    """Join a fixed query shape with values escaped by ``_quote``."""
    return "".join(parts)


def _required_text(*, record: Mapping[str, object], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise mailbox.LedgerRefusalError(_MISSING_RECORD_FIELD)
    return value


def _rows_affected(*, reply: object) -> int | None:
    if not isinstance(reply, dict):
        return None
    record = cast("dict[str, object]", reply)
    value = record.get("rows_affected")
    return value if type(value) is int else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def main(
    *,
    argv: Sequence[str] | None = None,
    connection: TenantConnection | None = None,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    now: Callable[[], str] = _now,
) -> int:
    """Run ``mailbox send`` or ``mailbox read`` against this tenant."""
    environment = os.environ if environ is None else environ
    sender = environment.get(_SEAT_NAME_ENV, "")
    if not sender:
        return 2
    ledger = BeadsMailboxLedger(connection=connection or BeadsTenantConnection(repo=Path.cwd()))
    return mailbox.main(
        argv=sys.argv[1:] if argv is None else argv,
        ledger=ledger,
        sender=sender,
        now=now,
        stdout=sys.stdout if stdout is None else stdout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
