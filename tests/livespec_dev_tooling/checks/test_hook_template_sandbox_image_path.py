"""The hook template preserves the PATH supplied by every sandbox image.

The pod-spec environment replaces an image's PATH rather than extending it.
This test removes the Rust layer's cargo directory from a copy of the real
template and expects the committed check to reject that image by name.  The
fixture copies the whole Dockerfile tree so a checker can discover layers and
resolve their ``FROM`` chain instead of maintaining a list of images here.
"""

from __future__ import annotations

import importlib
import shutil
from pathlib import Path
from types import ModuleType

import pytest

__all__: list[str] = []

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SANDBOX = _REPO_ROOT / "docker" / "fabro-sandbox"
_TEMPLATE = _REPO_ROOT / "ci-runner" / "k3s" / "phase2" / "arc" / "hook-pod-template.yaml"
_MODULE_PATH = (
    _REPO_ROOT / "livespec_dev_tooling" / "checks" / "hook_template_sandbox_image_path.py"
)


def _fixture_with_missing_cargo_path(*, root: Path) -> Path:
    """Copy the committed sources, except for one required template PATH entry."""
    shutil.copytree(_SANDBOX, root / "docker" / "fabro-sandbox")
    template = root / "ci-runner" / "k3s" / "phase2" / "arc" / "hook-pod-template.yaml"
    template.parent.mkdir(parents=True)
    template.write_text(
        _TEMPLATE.read_text(encoding="utf-8").replace("/root/.cargo/bin:", "", 1),
        encoding="utf-8",
    )
    return root


def _check() -> ModuleType:
    assert _MODULE_PATH.is_file(), (
        "the canonical hook-template sandbox PATH check must exist so `just check` can "
        "discover and run it"
    )
    return importlib.import_module("livespec_dev_tooling.checks.hook_template_sandbox_image_path")


def test_missing_sandbox_path_entry_fails_naming_the_image_and_entry(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A Rust image's cargo directory cannot disappear behind the pod-spec PATH."""
    root = _fixture_with_missing_cargo_path(root=tmp_path / "repo")
    monkeypatch.chdir(root)

    code = _check().main()

    stderr = capsys.readouterr().err
    assert code != 0
    assert "python-rust" in stderr
    assert "/root/.cargo/bin" in stderr
