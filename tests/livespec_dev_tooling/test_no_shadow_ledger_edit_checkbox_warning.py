"""Regression coverage for Edit-only checkbox flips in the shipped Stop hook."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

from livespec_dev_tooling.install_no_shadow_ledger import CANONICAL_NO_SHADOW_LEDGER_BODY

__all__: list[str] = []


def _render_hook(*, root: Path) -> ModuleType:
    """Render the wheel-carried hook body as the Drivers load it."""
    path = root / "no_shadow_ledger.py"
    _ = path.write_text(CANONICAL_NO_SHADOW_LEDGER_BODY, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("no_shadow_ledger_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run_hook(
    *,
    root: Path,
    entries: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str]:
    """Run a rendered hook against a synthetic transcript."""
    transcript = root / "transcript.jsonl"
    _ = transcript.write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8"
    )
    hook = _render_hook(root=root)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"transcript_path": str(transcript)})))
    return cast("int", hook.main()), capsys.readouterr().out


def _entries(*, name: str, tool_input: dict[str, object]) -> list[dict[str, object]]:
    """Return a real user turn followed by one file-persisting tool call."""
    return [
        {"type": "user", "message": {"content": "update the handoff"}},
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": name, "input": tool_input}]},
        },
    ]


def test_edit_checkbox_flip_warns_from_the_existing_planning_artifact(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An Edit's one checkbox flip warns when the file already has ten items."""
    handoff = tmp_path / "plan" / "topic" / "handoff.md"
    handoff.parent.mkdir(parents=True)
    _ = handoff.write_text(
        "\n".join(f"- [ ] task {number}" for number in range(10)) + "\n",
        encoding="utf-8",
    )
    rc, output = _run_hook(
        root=tmp_path,
        entries=_entries(
            name="Edit",
            tool_input={
                "file_path": str(handoff),
                "old_string": "- [ ] task 0",
                "new_string": "- [x] task 0",
            },
        ),
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert rc == 0
    assert output, "an Edit flipping one checkbox in a ten-item handoff must warn"
    warning = json.loads(output)

    assert "systemMessage" in warning
    assert "decision" not in warning


def test_edit_does_not_warn_for_an_existing_artifact_below_the_threshold(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reading post-edit content preserves the threshold for small handoffs."""
    handoff = tmp_path / "plan" / "topic" / "handoff.md"
    handoff.parent.mkdir(parents=True)
    _ = handoff.write_text("- [ ] first\n- [x] second\n", encoding="utf-8")

    rc, output = _run_hook(
        root=tmp_path,
        entries=_entries(
            name="Edit",
            tool_input={
                "file_path": str(handoff),
                "old_string": "- [ ] second",
                "new_string": "- [x] second",
            },
        ),
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert rc == 0
    assert output == ""


def test_write_with_ten_checkbox_items_still_warns(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The established Write detection continues to use written content."""
    handoff = tmp_path / "plan" / "topic" / "handoff.md"
    content = "\n".join(f"- [ ] task {number}" for number in range(10))

    rc, output = _run_hook(
        root=tmp_path,
        entries=_entries(name="Write", tool_input={"file_path": str(handoff), "content": content}),
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert rc == 0
    warning = json.loads(output)
    assert "systemMessage" in warning
    assert "decision" not in warning


def test_write_outside_planning_artifacts_does_not_warn(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The planning-artifact filter remains in front of checkbox detection."""
    document = tmp_path / "notes.md"
    content = "\n".join(f"- [ ] task {number}" for number in range(10))

    rc, output = _run_hook(
        root=tmp_path,
        entries=_entries(name="Write", tool_input={"file_path": str(document), "content": content}),
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert rc == 0
    assert output == ""


def test_unreadable_edited_file_is_a_silent_fail_open(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An Edit read failure does not block Stop or emit a decision."""
    handoff = tmp_path / "plan" / "topic" / "handoff.md"
    handoff.parent.mkdir(parents=True)
    _ = handoff.write_text("- [ ] task\n", encoding="utf-8")
    original_read_text = Path.read_text

    def fail_for_handoff(path: Path, *args: object, **kwargs: object) -> str:
        if path == handoff:
            raise OSError("unreadable")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_for_handoff)
    rc, output = _run_hook(
        root=tmp_path,
        entries=_entries(
            name="Edit",
            tool_input={
                "file_path": str(handoff),
                "old_string": "- [ ] task",
                "new_string": "- [x] task",
            },
        ),
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert rc == 0
    assert output == ""
