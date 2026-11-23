"""No-replacement recovery helpers for the Claude scratch mover."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

__all__: list[str] = [
    "put_back",
    "remove_partial_destination",
    "rename_without_replacement",
]


def rename_without_replacement(*, source: Path, destination: Path) -> bool:
    """Move only while the destination name remains absent."""
    if os.path.lexists(destination):
        return False
    try:
        status = os.spawnvp(  # noqa: S606 -- fixed argv, no shell
            os.P_WAIT, "mv", ["mv", "-n", "-T", "--", str(source), str(destination)]
        )
    except OSError:
        return False
    return status == 0 and not os.path.lexists(source)


def put_back(*, staging: Path, source: Path) -> str:
    """Restore staging without replacing a new directory at the source name."""
    if os.path.lexists(source):
        return "restore-blocked"
    if rename_without_replacement(source=staging, destination=source):
        return "restored"
    return "restore-blocked" if os.path.lexists(source) else "restore-incomplete"


def remove_partial_destination(*, destination: Path) -> None:
    """Delete a known partial-copy directory without following a symlink."""
    try:
        info = destination.lstat()
    except OSError:
        return
    if stat.S_ISDIR(info.st_mode):
        shutil.rmtree(destination)
