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

# ruff: noqa: SLF001

from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

__all__: list[str] = []


_REPO_ROOT = Path(__file__).resolve().parents[2]
_POLLER = (
    _REPO_ROOT / "ansible" / "roles" / "urgent_mailbox_poller" / "files" / "urgent-mailbox-poller"
)


def _load_poller():
    """Load the extensionless shipped program so coverage measures its control."""
    loader = SourceFileLoader("urgent_mailbox_poller_under_test", str(_POLLER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


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


def test_the_host_pollers_offline_control_is_covered_in_process(capsys) -> None:
    """Coverage must include the executable's alarm, dedupe, and outage rails."""
    poller = _load_poller()

    poller.self_test()

    assert "urgent-mailbox-poller self-test passed" in capsys.readouterr().out


def test_the_poller_recovers_from_bad_records_and_exercises_its_cli(  # noqa: PLR0915
    tmp_path, monkeypatch
) -> None:
    """Every sink failure remains local, while the next pass keeps the service alive."""
    poller = _load_poller()
    state_file = tmp_path / "state.json"
    alarm_file = tmp_path / "alarms.jsonl"
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")

    state_file.write_text("not-json", encoding="utf-8")
    assert poller._load_state(state_file) == {}
    state_file.write_text("[]", encoding="utf-8")
    assert poller._load_state(state_file) == {}
    assert poller._load_state(tmp_path / "missing-state.json") == {}
    poller._save_state(blocked / "state.json", {})
    assert not poller._append_alarm(
        blocked / "alarms.jsonl", message={"id": "broken-alarm"}, age=120
    )
    with pytest.raises(poller.LedgerError):
        poller._run([str(tmp_path / "missing-wrapper")], cwd=tmp_path)

    completed = subprocess.CompletedProcess([], 0, "[]", "")
    monkeypatch.setattr(poller, "_run", lambda *_args, **_kwargs: completed)
    assert poller.fetch_unread_urgent(wrapper="wrapper", cwd=tmp_path) == []
    poller.comment_on_coordinator(
        wrapper="wrapper",
        cwd=tmp_path,
        epic="coordinator",
        message={"id": "message", "from": "sender", "to": "seat"},
        age=121,
    )
    for output in ("not-json", "{}"):
        monkeypatch.setattr(
            poller,
            "_run",
            lambda *_args, output=output, **_kwargs: subprocess.CompletedProcess([], 0, output, ""),
        )
        with pytest.raises(poller.LedgerError):
            poller.fetch_unread_urgent(wrapper="wrapper", cwd=tmp_path)
    monkeypatch.setattr(
        poller,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, "", "unavailable"),
    )
    with pytest.raises(poller.LedgerError):
        poller.fetch_unread_urgent(wrapper="wrapper", cwd=tmp_path)
    with pytest.raises(poller.LedgerError):
        poller.comment_on_coordinator(
            wrapper="wrapper", cwd=tmp_path, epic="coordinator", message={"id": "message"}, age=121
        )

    assert poller._sent_at(None) is None
    assert poller._sent_at("not-a-time") is None
    assert poller._sent_at("2026-11-22T00:00:00") == datetime(2026, 11, 22, tzinfo=timezone.utc)
    with pytest.raises(RuntimeError, match="failed check"):
        poller._check(condition=False, message="failed check")

    overdue = {
        "id": "alarm-file-failure",
        "urgency": "urgent",
        "sent_at": "2026-11-22T00:00:00+00:00",
        "read_at": None,
    }
    monkeypatch.setattr(poller, "_append_alarm", lambda *_args, **_kwargs: False)
    poller.one_pass(
        now=datetime(2026, 11, 22, 0, 2, tzinfo=timezone.utc),
        dwell=120,
        alarm_file=alarm_file,
        state_file=tmp_path / "alarm-failure-state.json",
        fetch=lambda: ({"id": None}, overdue),
        comment=lambda *_args: pytest.fail("a failed alarm file must not create a ledger comment"),
    )

    monkeypatch.setattr(sys, "argv", ["urgent-mailbox-poller", "--self-test"])
    monkeypatch.setattr(poller, "self_test", lambda: None)
    assert poller.main() == 0
    monkeypatch.setattr(sys, "argv", ["urgent-mailbox-poller", "--dwell=-1"])
    assert poller.main() == 2
    calls: list[object] = []
    monkeypatch.setattr(poller, "one_pass", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(sys, "argv", ["urgent-mailbox-poller", "--once"])
    assert poller.main() == 0
    assert len(calls) == 1

    monkeypatch.setattr(
        poller.time, "sleep", lambda _seconds: (_ for _ in ()).throw(RuntimeError("stop"))
    )
    monkeypatch.setattr(sys, "argv", ["urgent-mailbox-poller", "--interval=1"])
    with pytest.raises(RuntimeError, match="stop"):
        poller.main()
