"""Consumer proof for the dev-host mailbox delivery hook.

The hook is deliberately exercised as Claude Code invokes it: the seat name is
read from the session's tmux name, ``mailbox`` is resolved from the host PATH,
and the only output is the UserPromptSubmit context-injection protocol object.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest
import yaml

__all__: list[str] = []

pytestmark = pytest.mark.consumer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ROLE = _REPO_ROOT / "ansible" / "roles" / "claude_code_hooks"
_HOOK = _ROLE / "files" / "mailbox-seat-read-hook.py"
_TASKS = _ROLE / "tasks" / "main.yml"


def _executable(*, path: Path, body: str) -> None:
    path.write_text(f"#!/bin/sh\nset -eu\n{body}", encoding="utf-8")
    path.chmod(0o755)


def _load_hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mailbox_seat_read_hook", _HOOK)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_installed_turn_hook_injects_unread_mail_for_its_session_seat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A host-installed turn boundary surfaces sender and urgency without a pane write."""
    assert _HOOK.is_file(), "claude_code_hooks must ship the mailbox turn hook"

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    mailbox_log = tmp_path / "mailbox.log"
    _executable(
        path=bin_dir / "mailbox",
        body=(
            'printf "%s\\n" "$*" > "$MAILBOX_LOG"\n'
            'printf \'%s\\n\' \'{"from": "coordinator", "urgency": "urgent", "body": "stop the roll"}\''
        ),
    )
    _executable(
        path=bin_dir / "tmux",
        body='test "$*" = "display-message -p #S"\nprintf "%s\\n" "mailbox-seat"',
    )
    monkeypatch.setenv("MAILBOX_LOG", str(mailbox_log))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,42,0")
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

    hook = _load_hook()
    main = cast("Callable[[], int]", hook.main)
    assert main() == 0

    assert mailbox_log.read_text(encoding="utf-8") == "read --me mailbox-seat\n"
    decision = cast("dict[str, object]", json.loads(capsys.readouterr().out))
    specific = cast("dict[str, str]", decision["hookSpecificOutput"])
    assert specific["hookEventName"] == "UserPromptSubmit"
    context = specific["additionalContext"]
    for text in ("coordinator", "urgent", "stop the roll"):
        assert text in context

    tasks = yaml.safe_load(_TASKS.read_text(encoding="utf-8"))
    assert "UserPromptSubmit" in str(tasks)
    assert "mailbox-seat-read-hook.py" in str(tasks)
