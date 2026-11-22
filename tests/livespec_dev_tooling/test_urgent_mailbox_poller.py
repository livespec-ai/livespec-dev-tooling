"""Acceptance coverage for the host-level urgent mailbox alarm.

The durable mailbox's normal delivery happens at a receiving seat's next turn
boundary.  This test holds the separate, host-level safety net to the first
definition-of-done assertion: after an urgent message remains unread past its
dwell, the poller must write every out-of-band alarm sink.  The poller owns its
own offline self-test so this test can exercise the installed executable shape
without reaching a Beads tenant, a host journal, or a pane.

Work-item: livespec-dev-tooling-f5upsw.  Plan: ledger-mailbox-seat-channel
(epic livespec-dev-tooling-4pa43l).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

__all__: list[str] = []


_REPO_ROOT = Path(__file__).resolve().parents[2]
_POLLER = (
    _REPO_ROOT / "ansible" / "roles" / "urgent_mailbox_poller" / "files" / "urgent-mailbox-poller"
)


def test_the_host_poller_alarms_an_unread_urgent_message_to_every_sink() -> None:
    """Its offline control proves journal, alarm-file, and coordinator-comment delivery.

    The subprocess is intentionally the role's shipped executable, rather than
    an imported helper: the executable is what Ansible installs as the host
    service, so a passing library-only test could not prove the host role has a
    runnable alarm path.
    """
    assert _POLLER.is_file(), (
        "the urgent mailbox poller must be a host-role executable beside the seat-dialog "
        "watchdog, so unread urgent messages can alarm even when a seat is stopped"
    )

    completed = subprocess.run(
        [str(_POLLER), "--self-test"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "urgent-mailbox-poller self-test passed" in completed.stdout
