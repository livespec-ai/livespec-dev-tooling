"""The reproduction queue's quotas are disarmed or one gate of one to two units.

`cluster-queue-repro-gates.yaml` holds one flavor per gate node. A repro gate is
a claim on a node the per-node CPU budget must count, so no flavor may carry a
partial gate unit or room for two concurrent repro gates. The unit is read from
the gates-cq annotations and no quota literal is asserted
(livespec-dev-tooling-cwrg3v).
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
_MEMORY = re.compile(r"^(?P<amount>0|[1-9][0-9]*)Gi$")


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
    """Each flavor selects one hostname, and exactly the two armed nodes have a flavor."""
    flavors = [
        d
        for d in _documents(name="cluster-queue-repro-gates.yaml")
        if d["kind"] == "ResourceFlavor"
    ]
    hosts = {str(f["spec"]["nodeLabels"]["kubernetes.io/hostname"]) for f in flavors}
    expected = {"poweredge-xubuntu", "gmktec-xubuntu"}
    assert hosts == expected, hosts


_RETIRED = ("gates-repro-gamingpc-flavor", "gates-repro-hp-flavor")
_CONVERGE = (
    Path(__file__).resolve().parents[2]
    / "ci-runner"
    / "k3s"
    / "phase2"
    / "reconstruct"
    / "converge-ci-stack.sh"
)


def test_the_retired_gamingpc_and_hp_repro_flavors_are_neither_defined_nor_listed() -> None:
    """No ResourceFlavor and no ClusterQueue quota entry names a retired repro flavor."""
    documents = _documents(name="cluster-queue-repro-gates.yaml")
    defined = {str(d["metadata"]["name"]) for d in documents if d["kind"] == "ResourceFlavor"}
    assert not defined & set(_RETIRED), defined
    assert not set(_repro_quotas()) & set(_RETIRED), _repro_quotas()


def test_the_converge_deletes_the_retired_repro_flavors_after_applying_the_queue() -> None:
    """The delete follows the cluster-queue apply loop and tolerates a flavor already gone.

    A flavor a ClusterQueue still lists cannot be deleted, so the delete must come after
    the loop that applies the edited gates-repro-cq, and a second run must not fail.
    """
    lines = _CONVERGE.read_text(encoding="utf-8").splitlines()
    applied = [i for i, line in enumerate(lines) if line.strip() == 'kubectl apply -f "$f"']
    deleted = [
        i
        for i, line in enumerate(lines)
        if line.startswith("kubectl delete resourceflavor") and "--ignore-not-found" in line
    ]
    assert applied, "the cluster-queue apply loop is gone"
    assert len(deleted) == 1, deleted
    assert all(name in lines[deleted[0]] for name in _RETIRED), lines[deleted[0]]
    assert deleted[0] > max(applied), (applied, deleted)


def test_the_node_budget_names_no_repro_lane_for_a_retired_flavor() -> None:
    """gamingpc-xubuntu and hp-xubuntu carry no repro_cpu once their flavors are retired."""
    nodes: dict[str, dict[str, Any]] = yaml.safe_load(_BUDGET.read_text(encoding="utf-8"))["nodes"]
    assert "repro_cpu" not in nodes["gamingpc-xubuntu"], nodes["gamingpc-xubuntu"]
    assert "repro_cpu" not in nodes["hp-xubuntu"], nodes["hp-xubuntu"]


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
    mismatched: dict[str, tuple[int, object]] = {}
    for name, (cpu, _memory) in _repro_quotas().items():
        match = _FLAVOR.match(name)
        assert match is not None, name
        budgeted = nodes[f"{match['node']}-xubuntu"].get("repro_cpu")
        if budgeted != cpu:
            mismatched[name] = (cpu, budgeted)
    assert not mismatched, mismatched
