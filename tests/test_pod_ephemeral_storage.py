"""The gate and factory pod classes request ephemeral-storage from committed values."""

from __future__ import annotations

from pathlib import Path

import yaml

__all__: list[str] = []

_PHASE2 = Path(__file__).resolve().parents[1] / "ci-runner" / "k3s" / "phase2"


def test_factory_namespace_defaults_every_sandbox_container_ephemeral_storage_request() -> None:
    """The factory LimitRange gives each container a 3Gi request and no limit."""
    documents = yaml.safe_load_all(
        (_PHASE2 / "factory" / "factory-namespace.yaml").read_text(encoding="utf-8")
    )
    ranges = [d for d in documents if d and d["kind"] == "LimitRange"]

    assert [r["metadata"]["namespace"] for r in ranges] == ["factory"]
    (container,) = ranges[0]["spec"]["limits"]
    assert container["type"] == "Container"
    assert container["defaultRequest"] == {"ephemeral-storage": "3Gi"}
    assert "default" not in container


def test_gate_template_requests_ephemeral_storage_without_a_limit() -> None:
    """The gate container requests the token and the memory-only limit is unchanged."""
    template = (_PHASE2 / "gates" / "gate-job-template.yaml").read_text(encoding="utf-8")

    assert 'ephemeral-storage: "@@EPHEMERAL_STORAGE@@"' in template
    assert template.count("@@EPHEMERAL_STORAGE@@") == 1


def test_measurement_doc_records_both_requests() -> None:
    """The measurement sits beside the values it derives."""
    doc = (_PHASE2 / "EPHEMERAL-STORAGE.md").read_text(encoding="utf-8")

    assert "| 2560Mi |" in doc
    assert "| 3Gi |" in doc
