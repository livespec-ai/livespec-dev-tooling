"""The repro queue retains only the two active per-node routes.

The gamingpc and hp reproduction ResourceFlavors are retired while gmktec and
poweredge remain available to the explicit ``gate-repro`` route
(livespec-dev-tooling-nkocp5).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.integration

_REPRO_QUEUE = (
    Path(__file__).resolve().parents[2]
    / "ci-runner"
    / "k3s"
    / "phase2"
    / "kueue"
    / "cluster-queue-repro-gates.yaml"
)
_ACTIVE_FLAVORS = {"gates-repro-gmktec-flavor", "gates-repro-poweredge-flavor"}


def _documents() -> list[dict[str, Any]]:
    return [
        document
        for document in yaml.safe_load_all(_REPRO_QUEUE.read_text(encoding="utf-8"))
        if document is not None
    ]


def test_repro_queue_declares_only_the_active_per_node_flavors() -> None:
    """Retired gamingpc and hp flavors cannot remain in source or the ClusterQueue."""
    documents = _documents()
    declared = {
        str(document["metadata"]["name"])
        for document in documents
        if document["kind"] == "ResourceFlavor"
    }
    [queue] = [
        document
        for document in documents
        if document["kind"] == "ClusterQueue" and document["metadata"]["name"] == "gates-repro-cq"
    ]
    queued = {
        str(flavor["name"])
        for group in queue["spec"]["resourceGroups"]
        for flavor in group["flavors"]
    }

    assert declared == _ACTIVE_FLAVORS
    assert queued == _ACTIVE_FLAVORS
