"""The active reproduction route's quotas and retirement converge.

`cluster-queue-repro-gates.yaml` holds flavors only for the active gmktec and
poweredge routes. A repro gate is a claim on a node the per-node CPU budget
must count, so no flavor may carry a partial gate unit or room for two
concurrent repro gates. The unit is read from the gates-cq annotations and no
quota literal is asserted (livespec-dev-tooling-cwrg3v).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

__all__: list[str] = []

pytestmark = pytest.mark.integration

_KUEUE = Path(__file__).resolve().parents[2] / "ci-runner" / "k3s" / "phase2" / "kueue"
_CONVERGE = _KUEUE.parent / "reconstruct" / "converge-ci-stack.sh"
_MEMORY = re.compile(r"^(?P<amount>0|[1-9][0-9]*)Gi$")
_ACTIVE_HOSTS = {"gmktec-xubuntu", "poweredge-xubuntu"}
_RETIRED_DELETE = "kubectl delete resourceflavor gates-repro-gamingpc-flavor gates-repro-hp-flavor \\\n  --ignore-not-found --wait=false"


def _documents(*, name: str) -> list[dict[str, Any]]:
    loaded: list[dict[str, Any] | None] = list(
        yaml.safe_load_all((_KUEUE / name).read_text(encoding="utf-8"))
    )
    return [document for document in loaded if document]


def _unit() -> tuple[int, int]:
    [queue] = [
        d
        for d in _documents(name="cluster-queue-gates.yaml")
        if d["kind"] == "ClusterQueue" and d["metadata"]["name"] == "gates-cq"
    ]
    annotations: dict[str, str] = queue["metadata"]["annotations"]
    memory = _MEMORY.match(annotations["ci-runner.io/gate-unit-memory"])
    assert memory is not None
    return int(annotations["ci-runner.io/gate-unit-cpu"]), int(memory["amount"])


def _repro_quotas() -> dict[str, tuple[int, int]]:
    [queue] = [
        d for d in _documents(name="cluster-queue-repro-gates.yaml") if d["kind"] == "ClusterQueue"
    ]
    quotas: dict[str, tuple[int, int]] = {}
    for group in queue["spec"]["resourceGroups"]:
        for flavor in group["flavors"]:
            by_name = {str(r["name"]): r["nominalQuota"] for r in flavor["resources"]}
            memory = _MEMORY.match(str(by_name["memory"]))
            assert memory is not None, flavor["name"]
            quotas[str(flavor["name"])] = (int(by_name["cpu"]), int(memory["amount"]))
    return quotas


def test_every_repro_flavor_is_disarmed_or_admits_one_gate_of_at_most_two_units() -> None:
    """A repro flavor is zero, or holds one gate: at least one unit, at most two units.

    The bounds are derived from the gates-cq unit, so a repository declaring a larger
    gate_cpu can be admitted without the test pinning any committed quota value.
    """
    unit_cpu, unit_memory = _unit()
    off_shape = {
        name: (cpu, memory)
        for name, (cpu, memory) in _repro_quotas().items()
        if (cpu, memory) != (0, 0)
        and not (unit_cpu <= cpu <= 2 * unit_cpu and unit_memory <= memory <= 2 * unit_memory)
    }
    assert not off_shape, (unit_cpu, unit_memory, off_shape)


def test_every_repro_flavor_is_pinned_to_its_node_by_hostname() -> None:
    """Each active flavor selects exactly one hostname."""
    flavors = [
        d
        for d in _documents(name="cluster-queue-repro-gates.yaml")
        if d["kind"] == "ResourceFlavor"
    ]
    hosts = {str(f["spec"]["nodeLabels"]["kubernetes.io/hostname"]) for f in flavors}
    assert hosts == _ACTIVE_HOSTS, hosts


_BUDGET = (
    Path(__file__).resolve().parents[2] / "ci-runner" / "k3s" / "phase2" / "node-cpu-budget.yaml"
)
_FLAVOR = re.compile(r"^gates-repro-(?P<node>[a-z0-9]+)-flavor$")


def test_every_repro_flavor_quota_equals_its_nodes_budgeted_repro_cpu() -> None:
    """A repro flavor's cpu quota is the repro lane its node's committed budget names.

    The budget counts a repro gate as a CPU claim on the node, so a flavor cannot be
    armed, raised or disarmed without the budget naming it. The values are read from
    both files; no literal is asserted.
    """
    nodes: dict[str, dict[str, Any]] = yaml.safe_load(_BUDGET.read_text(encoding="utf-8"))["nodes"]
    budgeted_hosts = {name for name, node in nodes.items() if "repro_cpu" in node}
    assert budgeted_hosts == _ACTIVE_HOSTS, budgeted_hosts
    mismatched: dict[str, tuple[int, object]] = {}
    for name, (cpu, _memory) in _repro_quotas().items():
        match = _FLAVOR.match(name)
        assert match is not None, name
        budgeted = nodes[f"{match['node']}-xubuntu"].get("repro_cpu")
        if budgeted != cpu:
            mismatched[name] = (cpu, budgeted)
    assert not mismatched, mismatched


def test_converge_applies_the_edited_queues_before_idempotently_deleting_retired_flavors() -> None:
    """Apply removes ClusterQueue references before cleanup removes the objects."""
    converge = _CONVERGE.read_text(encoding="utf-8")
    queue_apply = 'kubectl apply -f "$f"'
    assert _RETIRED_DELETE in converge
    assert converge.index(_RETIRED_DELETE) > converge.index(queue_apply)
