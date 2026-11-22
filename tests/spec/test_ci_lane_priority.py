"""CI-priority runner-set manifests preserve a normal-priority lane."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

__all__: list[str] = []

_ARC = Path(__file__).resolve().parents[2] / "ci-runner" / "k3s" / "phase2" / "arc"
_NORMAL_VALUES = sorted(
    path
    for path in _ARC.glob("values-*.yaml")
    if path.name != "values-EXAMPLE-repo.yaml" and not path.stem.endswith("-priority")
)


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_every_normal_runner_set_declares_ci_normal_workload_priority() -> None:
    """Normal lanes declare the lower class that their priority siblings outrank."""
    missing = [
        path.name
        for path in _NORMAL_VALUES
        if _load(path)
        .get("template", {})
        .get("metadata", {})
        .get("labels", {})
        .get("kueue.x-k8s.io/priority-class")
        != "ci-normal"
    ]

    assert not missing, (
        "normal runner-set manifest(s) must label their pods with "
        f"kueue.x-k8s.io/priority-class=ci-normal: {missing}"
    )
