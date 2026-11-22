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
    transcript = tmp_path / "transcript.jsonl"
    entries = [
        {"type": "user", "message": {"content": "mark task complete"}},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Edit",
                        "input": {
                            "file_path": str(handoff),
                            "old_string": "- [ ] task 0",
                            "new_string": "- [x] task 0",
                        },
                    }
                ]
            },
        },
    ]
    _ = transcript.write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8"
    )
    hook = _render_hook(root=tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"transcript_path": str(transcript)})))

    assert cast("int", hook.main()) == 0
    output = capsys.readouterr().out
    assert output, "an Edit flipping one checkbox in a ten-item handoff must warn"
    warning = json.loads(output)

    assert "systemMessage" in warning
