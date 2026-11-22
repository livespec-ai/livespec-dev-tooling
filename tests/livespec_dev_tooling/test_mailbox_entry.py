"""Acceptance coverage for the tenant-backed mailbox command entry."""

from __future__ import annotations

from pathlib import Path

from livespec_dev_tooling import mailbox


def test_mailbox_has_a_runnable_tenant_backed_entry() -> None:
    """The injected mailbox library is surfaced through a real tenant command entry."""
    entry = Path(mailbox.__file__).with_name("mailbox_entry.py")

    assert entry.is_file(), (
        "mailbox send/read needs a runnable entry that binds the injected library "
        "to the Beads tenant connection"
    )
