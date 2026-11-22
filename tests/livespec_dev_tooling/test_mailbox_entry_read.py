"""The runnable mailbox read entry needs no sender identity."""

from __future__ import annotations

from io import StringIO

from livespec_dev_tooling import mailbox_entry


class _EmptyTenant:
    """A stand-in tenant holding no unread mail."""

    def execute(self, *, sql: str) -> object:
        if sql.startswith("SELECT"):
            return []
        return {"status": "ok"}


def test_read_runs_without_a_sender_seat_in_the_environment() -> None:
    """`mailbox read --me <seat>` supplies the reader itself, so no sender env is required."""
    status = mailbox_entry.main(
        argv=("read", "--me", "recipient"),
        connection=_EmptyTenant(),
        environ={},
        stdout=StringIO(),
    )

    assert status == 0
