"""Refuse a gate Job whose queue cannot admit what the Job asks for.

On 2026-11-21 a gate Job requesting `ephemeral-storage` was submitted to
`gates-cq`, a StrictFIFO ClusterQueue whose `coveredResources` were only `cpu`
and `memory`. Kueue never admits a Workload that requests a resource no
resource group of its ClusterQueue covers ("resource ephemeral-storage
unavailable in ClusterQueue"), and a StrictFIFO queue does not skip a head that
cannot be admitted, so that one Job held every later gate in the fleet Pending.
Nothing errored: the Job simply never ran.

This is the pre-submit half of the fix. It runs BEFORE the `create`, reads the
LocalQueue the manifest names, then the ClusterQueue that LocalQueue points at,
and refuses a manifest that requests (or limits) a resource the ClusterQueue
does not cover. The other half is the committed queues, which cover
`ephemeral-storage` beside `cpu` and `memory`; this check is what keeps the
NEXT resource a template starts to request from wedging the line the same way.

A read it cannot take LETS THE SUBMIT PROCEED. The check is a guard against a
known wedge, not a gate on the cluster's health: a refused `get`, an absent
`kubectl`, or an answer it cannot parse means the coverage is unknown, and
refusing every gate because the API server hiccuped would be a worse outage than
the one this prevents.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

from returns.result import Failure

from livespec_dev_tooling.gate_credential import with_gates_kubeconfig
from livespec_dev_tooling.gate_remote_invocation import (
    GateCommandRunner,
    GateStepFailed,
)
from livespec_dev_tooling.gate_remote_request import GateRunRequest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

_VENDOR_DIR = Path(__file__).resolve().parent / "_vendor"
if str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

__all__: list[str] = ["COVERAGE_STEP", "uncovered_requests"]

COVERAGE_STEP = "check-queue-covers-requests"

_QUEUE_LABEL = "kueue.x-k8s.io/queue-name"

# A private name that cannot shadow a consumer's own `yaml`, as in
# `_gate_lane_capacity`.
_YAML = importlib.import_module("livespec_yaml")
_LOAD_ALL = cast("Callable[[str], Iterable[object]]", _YAML.safe_load_all)
_YAML_ERROR = cast("type[Exception]", _YAML.YAMLError)


def uncovered_requests(
    *, request: GateRunRequest, runner: GateCommandRunner
) -> GateStepFailed | None:
    """Return a refusal naming each requested resource the queue does not cover.

    `None` means submit: the manifest names no queue or requests nothing, every
    requested resource is covered, or the coverage could not be read.
    """
    queue = _queue_and_requests(manifest=request.manifest)
    if queue is None:
        return None
    local_queue, requested = queue
    cluster_queue = _cluster_queue_of(request=request, runner=runner, local_queue=local_queue)
    if cluster_queue is None:
        return None
    covered = _covered_resources(request=request, runner=runner, cluster_queue=cluster_queue)
    if covered is None:
        return None
    missing = sorted(requested - covered)
    if not missing:
        return None
    return GateStepFailed(
        step=COVERAGE_STEP,
        argv=("kueue-coverage", local_queue, cluster_queue),
        returncode=1,
        detail=(
            f"the gate Job requests {', '.join(missing)}, which ClusterQueue {cluster_queue} "
            f"(LocalQueue {local_queue}) does not cover; Kueue would never admit it, and the "
            "queue is StrictFIFO, so it would hold every later gate Pending. Cover the resource "
            f"in {cluster_queue} through the committed queue manifest and its converge BEFORE "
            "any client requests it."
        ),
    )


def _mapping(*, value: object) -> dict[str, object]:
    """The value as a string-keyed mapping, or an empty one when it is not a mapping."""
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def _sequence(*, value: object) -> list[object]:
    """The value as a list, or an empty one when it is not a list."""
    return cast("list[object]", value) if isinstance(value, list) else []


def _queue_and_requests(*, manifest: str) -> tuple[str, frozenset[str]] | None:
    """The LocalQueue name and every resource name the Job's containers ask for."""
    try:
        documents = list(_LOAD_ALL(manifest))
    except _YAML_ERROR:
        return None
    for document in documents:
        job = _mapping(value=document)
        label = _mapping(value=_mapping(value=job.get("metadata")).get("labels")).get(_QUEUE_LABEL)
        queue = label if isinstance(label, str) else ""
        requested = _requested_resources(job=job)
        if queue and requested:
            return queue, requested
    return None


def _requested_resources(*, job: dict[str, object]) -> frozenset[str]:
    pod = _mapping(
        value=_mapping(value=_mapping(value=job.get("spec")).get("template")).get("spec")
    )
    names: set[str] = set()
    for key in ("containers", "initContainers"):
        for container in _sequence(value=pod.get(key)):
            resources = _mapping(value=_mapping(value=container).get("resources"))
            for section in ("requests", "limits"):
                names.update(_mapping(value=resources.get(section)))
    return frozenset(names)


def _read_json(
    *, request: GateRunRequest, runner: GateCommandRunner, kind: str, name: str
) -> dict[str, object]:
    """One queue object as a mapping; empty when the read could not be taken."""
    argv = [
        *with_gates_kubeconfig(argv=["kubectl", "--namespace", request.namespace]),
        "get",
        kind,
        name,
        "--output",
        "json",
    ]
    outcome = runner(argv=argv, cwd=request.repo_root)
    if isinstance(outcome, Failure) or outcome.unwrap().returncode != 0:
        return {}
    try:
        return _mapping(value=cast("object", json.loads(outcome.unwrap().stdout)))
    except json.JSONDecodeError:
        return {}


def _cluster_queue_of(
    *, request: GateRunRequest, runner: GateCommandRunner, local_queue: str
) -> str | None:
    read = _read_json(request=request, runner=runner, kind="localqueue", name=local_queue)
    name = _mapping(value=read.get("spec")).get("clusterQueue")
    return name if isinstance(name, str) and name else None


def _covered_resources(
    *, request: GateRunRequest, runner: GateCommandRunner, cluster_queue: str
) -> frozenset[str] | None:
    read = _read_json(request=request, runner=runner, kind="clusterqueue", name=cluster_queue)
    groups = _mapping(value=read.get("spec")).get("resourceGroups")
    if not isinstance(groups, list):
        return None
    covered: set[str] = set()
    for group in _sequence(value=cast("object", groups)):
        covered.update(
            str(name) for name in _sequence(value=_mapping(value=group).get("coveredResources"))
        )
    return frozenset(covered)
