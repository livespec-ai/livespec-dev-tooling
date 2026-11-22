"""Acceptance coverage for orphaned red-green-replay signing-key fixtures."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_MODULE = _REPO_ROOT / "tests/livespec_dev_tooling/checks/test_red_green_replay_revert.py"


def _fixture_helpers() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rgr_fixture_helpers", _FIXTURE_MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_new_signing_key_sweeps_a_forge_home_left_by_a_dead_creator(
    *, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A new fixture run removes a recorded key home from a killed pytest session."""
    fixture_helpers = _fixture_helpers()
    stale_home = tmp_path / "rgr-forge-key-killed-session"
    stale_home.mkdir()
    (stale_home / ".rgr-forge-creator.json").write_text(
        json.dumps({"pid": 999_999_999, "start_time": "0"}), encoding="utf-8"
    )
    new_home = tmp_path / "rgr-forge-key-new-session"

    def fake_gpg(*, home: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        del home
        if "--with-colons" in args:
            stdout = "fpr:::::::::TEST-FINGERPRINT:\n"
        elif "--export" in args:
            stdout = "fixture public key"
        else:
            stdout = ""
        return subprocess.CompletedProcess(args=["gpg", *args], returncode=0, stdout=stdout)

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **_: str(new_home))
    monkeypatch.setattr(fixture_helpers, "_gpg", fake_gpg)

    key = fixture_helpers._new_signing_key(  # noqa: SLF001 - acceptance test targets this fixture helper.
        uid="Replacement Fixture <fixture@example.invalid>"
    )

    assert key.home == new_home
    assert not stale_home.exists()
