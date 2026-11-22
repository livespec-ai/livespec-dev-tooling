"""Import coverage for the runnable tenant-backed mailbox entry."""

from __future__ import annotations

from pathlib import Path

from livespec_dev_tooling import mailbox_entry


def test_mailbox_entry_module_is_importable() -> None:
    """The package exposes the mailbox command module to its console script."""
    assert Path(mailbox_entry.__file__).is_file()
