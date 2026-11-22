"""The incident hook refuses a missing, empty or unusable check-targets.txt by name."""

from __future__ import annotations

from pathlib import Path

import pytest

from livespec_dev_tooling import incident_hook_entry as module
from tests.livespec_dev_tooling.test_incident_hook_entry_edges import _wired


def _refusal(
    *,
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    text: str | None,
    capfd: pytest.CaptureFixture[str],
) -> tuple[int, str, bool]:
    _reading, receipts = _wired(root=root, monkeypatch=monkeypatch, inventory=False)
    if text is not None:
        (root / "check-targets.txt").write_text(text)
        (root / ".git" / "info" / "exclude").write_text("check-targets.txt\n")
    status = module.main(argv=["pre-commit"])
    return status, capfd.readouterr().err, bool(receipts)


def test_undeclared_inventory_refusal_names_the_remedy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    status, err, receipted = _refusal(
        root=tmp_path, monkeypatch=monkeypatch, text=None, capfd=capfd
    )
    assert all(
        [
            status == 78,
            "incident-inventory-undeclared" in err,
            "commit a measured check-targets.txt" in err,
            "# incident-timing:" in err,
            not receipted,
        ]
    )


def test_real_zero_byte_inventory_fails_closed_with_a_named_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    status, err, receipted = _refusal(root=tmp_path, monkeypatch=monkeypatch, text="", capfd=capfd)
    assert all(
        [
            status == 78,
            "incident-inventory-empty" in err,
            "Traceback" not in err,
            not receipted,
        ]
    )


def test_all_malformed_inventory_fails_closed_with_a_named_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    status, err, receipted = _refusal(
        root=tmp_path,
        monkeypatch=monkeypatch,
        text="not a recipe!!\n$(boom) # incident-timing: fast\n",
        capfd=capfd,
    )
    assert all(
        [
            status == 78,
            "incident-inventory-unusable-member" in err,
            "Traceback" not in err,
            not receipted,
        ]
    )
