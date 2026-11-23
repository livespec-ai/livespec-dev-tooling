"""Default-branch CI facts that can make an incident adopter unsafe to enable."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from livespec_dev_tooling.incident_ci_inventory import (
    InventoryUndeclaredError,
    load_repository_inventory,
)
from livespec_dev_tooling.incident_matrix_call_site import load_workflow

__all__: list[str] = ["workflow_findings"]

_OBSERVER_INPUTS = (
    "LIVESPEC_INCIDENT_OBSERVER_URL",
    "LIVESPEC_INCIDENT_OBSERVER_CONNECT_ADDR",
    "LIVESPEC_INCIDENT_OBSERVER_QUERY_TOKEN",
)
_TAILNET_LABELS = ("local-ci", "k3s")


def _mapping(*, value: object) -> Mapping[str, Any]:
    return cast("Mapping[str, Any]", value) if isinstance(value, dict) else {}


def _steps(*, job: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    value = job.get("steps")
    return (
        tuple(_mapping(value=step) for step in cast("list[object]", value))
        if isinstance(value, list)
        else ()
    )


def _runs_replay(*, job: Mapping[str, Any]) -> bool:
    return any("check-red-green-replay" in str(step.get("run", "")) for step in _steps(job=job))


def _tailnet_reachable(*, runs_on: object) -> bool:
    expression = str(runs_on)
    return "self-hosted" in expression and any(label in expression for label in _TAILNET_LABELS)


def _routing_findings(*, repository: str, jobs: Mapping[str, Any]) -> tuple[str, ...]:
    findings: list[str] = []
    for name, value in jobs.items():
        job = _mapping(value=value)
        if str(name) != "incident-ci" and not _runs_replay(job=job):
            continue
        runs_on = job.get("runs-on", "")
        if not _tailnet_reachable(runs_on=runs_on):
            findings.append(
                "".join(
                    (
                        f"{repository}: job {name} runs-on {runs_on!s} ",
                        "has no tailnet-reaching label set",
                    )
                )
            )
    return tuple(findings)


def _observer_input_findings(*, repository: str, jobs: Mapping[str, Any]) -> tuple[str, ...]:
    findings: list[str] = []
    for name, value in jobs.items():
        job = _mapping(value=value)
        for step in _steps(job=job):
            if "check-red-green-replay" not in str(step.get("run", "")):
                continue
            env = _mapping(value=step.get("env"))
            for input_name in _OBSERVER_INPUTS:
                if input_name not in env:
                    findings.append(
                        "".join(
                            (
                                f"{repository}: job {name} check-red-green-replay lacks ",
                                input_name,
                            )
                        )
                    )
    return tuple(findings)


def _inventory_findings(*, repository: str, jobs: Mapping[str, Any]) -> tuple[str, ...]:
    try:
        not_applicable = tuple(
            target.name
            for target in load_repository_inventory(repository=repository)
            if target.classification == "not-applicable"
        )
    except (InventoryUndeclaredError, ValueError):
        return (f"{repository}: released incident CI inventory is unavailable",)
    findings: list[str] = []
    for member in not_applicable:
        for name, value in jobs.items():
            job = _mapping(value=value)
            body = str(job)
            if member in body and "omitted-by-incident-policy" not in body:
                findings.append(
                    "".join(
                        (
                            f"{repository}: job {name} runs not-applicable member {member}",
                            " on an incident pull request without an incident-policy omission",
                        )
                    )
                )
    return tuple(findings)


def workflow_findings(*, repository: str, workflow: str | None) -> tuple[str, ...]:
    """Return readiness blockers from an adopter's committed ``ci.yml``."""
    parsed = None if workflow is None else load_workflow(text=workflow)
    jobs = _mapping(value=_mapping(value=parsed).get("jobs"))
    if not jobs:
        return (f"{repository}: default-branch ci.yml is unavailable or has no jobs",)
    return (
        *_routing_findings(repository=repository, jobs=jobs),
        *_observer_input_findings(repository=repository, jobs=jobs),
        *_inventory_findings(repository=repository, jobs=jobs),
    )
