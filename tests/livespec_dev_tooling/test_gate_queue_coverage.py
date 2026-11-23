"""A gate Job may not be submitted to a queue that cannot admit what it asks for.

On 2026-11-21 a gate Job requesting `ephemeral-storage` was submitted to
`gates-cq`, a StrictFIFO ClusterQueue whose `coveredResources` were only `cpu`
and `memory`. Kueue never admits such a Workload ("resource ephemeral-storage
unavailable in ClusterQueue"), and because the queue is StrictFIFO it sat at the
head of the line and held every later gate in the fleet Pending. Nothing
errored: the Job simply never ran.

The client now reads the queue the manifest names and refuses, BEFORE the
create, a manifest that requests a resource the queue does not cover. A read it
cannot take lets the submit proceed, because a gate that cannot be checked is
not a gate that may not run.
"""

from __future__ import annotations

import json
from pathlib import Path

from returns.pipeline import is_successful
from returns.result import Failure, Success

from livespec_dev_tooling._gate_queue_coverage import COVERAGE_STEP, uncovered_requests
from livespec_dev_tooling.gate_remote_client import run_gate
from livespec_dev_tooling.gate_remote_invocation import (
    GateCommandNotRun,
    GateCommandOutcome,
    GateCommandResult,
)
from livespec_dev_tooling.gate_remote_request import GateRunRequest

__all__: list[str] = []

_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_PLAIN = "cpu: '5'\n              memory: 8Gi"
_EPHEMERAL = "cpu: '5'\n              memory: 8Gi\n              ephemeral-storage: 2560Mi"


def _manifest(*, queue: str | None = "gates-lq", requests: str = _PLAIN, limits: str = "") -> str:
    label = f"    kueue.x-k8s.io/queue-name: {queue}\n" if queue else "    app: gate\n"
    limit_block = f"            limits:\n              {limits}\n" if limits else ""
    return (
        "apiVersion: batch/v1\nkind: Job\nmetadata:\n  generateName: gate-widget-\n"
        f"  labels:\n{label}"
        "spec:\n  template:\n    spec:\n      initContainers:\n        - name: fetch\n"
        "          image: x\n      containers:\n        - name: gate\n          image: x\n"
        f"          resources:\n            requests:\n              {requests}\n{limit_block}"
    )


def _request(*, manifest: str) -> GateRunRequest:
    return GateRunRequest(
        repo_root=Path("/repo"),
        mirror_url="host:/mirror/widget.git",
        manifest=manifest,
        gate_ref=f"refs/gates/{_TREE}-4c1d9f3b2a7e",
        tree_hash=_TREE,
    )


class _Cluster:
    """A canned cluster: the LocalQueue, the ClusterQueue and nothing else."""

    def __init__(
        self,
        *,
        covered: tuple[tuple[str, ...], ...] = (("cpu", "memory"),),
        local_rc: int = 0,
        cluster_rc: int = 0,
        local_out: str | None = None,
        cluster_out: str | None = None,
    ) -> None:
        self.argvs: list[tuple[str, ...]] = []
        self._covered = covered
        self._local_rc = local_rc
        self._cluster_rc = cluster_rc
        self._local_out = local_out
        self._cluster_out = cluster_out

    def __call__(
        self,
        *,
        argv: list[str],
        cwd: Path,
        stdin: str | None = None,
        stream: bool = False,
    ) -> GateCommandOutcome:
        _ = (cwd, stdin, stream)
        self.argvs.append(tuple(argv))
        if "localqueue" in argv:
            out = self._local_out or json.dumps({"spec": {"clusterQueue": "gates-cq"}})
            return Success(GateCommandResult(returncode=self._local_rc, stdout=out, stderr="nope"))
        if "clusterqueue" in argv:
            groups = [{"coveredResources": list(group)} for group in self._covered]
            out = self._cluster_out or json.dumps({"spec": {"resourceGroups": groups}})
            return Success(
                GateCommandResult(returncode=self._cluster_rc, stdout=out, stderr="nope")
            )
        return Success(GateCommandResult(returncode=0, stdout="", stderr=""))


def test_a_request_for_an_uncovered_resource_is_refused_naming_resource_and_queue() -> None:
    refusal = uncovered_requests(
        request=_request(manifest=_manifest(requests=_EPHEMERAL)), runner=_Cluster()
    )

    assert refusal is not None
    assert refusal.step == COVERAGE_STEP
    assert "ephemeral-storage" in refusal.detail
    assert "gates-cq" in refusal.detail
    assert "gates-lq" in refusal.detail


def test_a_request_the_queue_covers_is_not_refused() -> None:
    assert uncovered_requests(request=_request(manifest=_manifest()), runner=_Cluster()) is None


def test_resources_covered_across_several_resource_groups_are_all_covered() -> None:
    cluster = _Cluster(covered=(("cpu",), ("memory", "ephemeral-storage")))

    assert (
        uncovered_requests(
            request=_request(manifest=_manifest(requests=_EPHEMERAL)), runner=cluster
        )
        is None
    )


def test_a_limit_alone_counts_as_a_request_of_that_resource() -> None:
    manifest = _manifest(limits="ephemeral-storage: 4Gi")

    refusal = uncovered_requests(request=_request(manifest=manifest), runner=_Cluster())

    assert refusal is not None
    assert "ephemeral-storage" in refusal.detail


def test_a_manifest_naming_no_queue_reads_nothing_and_is_not_refused() -> None:
    cluster = _Cluster()

    assert (
        uncovered_requests(request=_request(manifest=_manifest(queue=None)), runner=cluster) is None
    )
    assert cluster.argvs == []


def test_a_manifest_that_is_not_a_job_with_resources_is_not_refused() -> None:
    cluster = _Cluster()
    bare = (
        "apiVersion: batch/v1\nkind: Job\nmetadata:\n  labels:\n"
        "    kueue.x-k8s.io/queue-name: gates-lq\n"
    )

    assert uncovered_requests(request=_request(manifest=bare), runner=cluster) is None
    assert uncovered_requests(request=_request(manifest="- a\n- list\n"), runner=cluster) is None
    assert uncovered_requests(request=_request(manifest="key: [unclosed\n"), runner=cluster) is None


def test_a_queue_read_that_cannot_be_taken_lets_the_submit_proceed() -> None:
    request = _request(manifest=_manifest(requests=_EPHEMERAL))
    for cluster in (
        _Cluster(local_rc=1),
        _Cluster(cluster_rc=1),
        _Cluster(local_out="not json"),
        _Cluster(cluster_out="not json"),
        _Cluster(local_out=json.dumps({"spec": {}})),
        _Cluster(cluster_out=json.dumps({"spec": {"resourceGroups": "bad"}})),
    ):
        assert uncovered_requests(request=request, runner=cluster) is None


def test_a_queue_read_that_never_ran_lets_the_submit_proceed() -> None:
    def never_ran(
        *, argv: list[str], cwd: Path, stdin: str | None = None, stream: bool = False
    ) -> GateCommandOutcome:
        _ = (cwd, stdin, stream)
        return Failure(GateCommandNotRun(argv=tuple(argv), detail="kubectl not on PATH"))

    request = _request(manifest=_manifest(requests=_EPHEMERAL))

    assert uncovered_requests(request=request, runner=never_ran) is None


def test_run_gate_refuses_before_any_job_is_created() -> None:
    cluster = _Cluster()

    outcome = run_gate(
        request=_request(manifest=_manifest(requests=_EPHEMERAL)),
        runner=cluster,
        sleeper=lambda **_: None,
    )

    assert not is_successful(outcome)
    assert outcome.failure().step == COVERAGE_STEP
    assert not [argv for argv in cluster.argvs if "create" in argv]


def test_run_gate_submits_when_the_queue_covers_the_request() -> None:
    cluster = _Cluster()

    _ = run_gate(request=_request(manifest=_manifest()), runner=cluster, sleeper=lambda **_: None)

    assert [argv for argv in cluster.argvs if "create" in argv and "kubectl" in argv]
