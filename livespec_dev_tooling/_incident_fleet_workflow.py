"""Default-branch CI facts that can make an incident adopter unsafe to enable."""

from __future__ import annotations

import re
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
_OMITTED_OUTPUT = "outputs.omitted"
_OMISSION_MARKER = "omitted_by_incident_policy"


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


def _names(*, member: str, text: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(member)}(?![\w-])", text) is not None


def _omission_condition(*, member: str, condition: object, matrix: str) -> bool:
    text = str(condition)
    return _OMITTED_OUTPUT in text and (_names(member=member, text=text) or matrix in text)


def _bound_omission_variables(*, step: Mapping[str, Any]) -> tuple[str, ...]:
    env = _mapping(value=step.get("env"))
    return tuple(key for key, value in env.items() if _OMITTED_OUTPUT in str(value))


def _shell_guarded(*, member: str, step: Mapping[str, Any]) -> bool:
    variables = _bound_omission_variables(step=step)
    if not variables:
        return False
    for line in str(step.get("run", "")).splitlines():
        if not _names(member=member, text=line):
            continue
        referenced = _OMISSION_MARKER in line.lower().replace("-", "_") or any(
            variable in line for variable in variables
        )
        if not (referenced and any(operator in line for operator in ("||", "&&", "if "))):
            return False
    return True


def _step_runs_member(*, member: str, step: Mapping[str, Any], member_job: bool) -> bool:
    text = f"{step.get('run', '')} {step.get('uses', '')} {step.get('with', '')}"
    executes = bool(step.get("run") or step.get("uses"))
    return executes and (member_job or _names(member=member, text=text))


def _job_omits_member(*, member: str, name: object, job: Mapping[str, Any]) -> bool:
    if "uses" in job:
        return _OMITTED_OUTPUT in str(_mapping(value=job.get("with")).get("incident-omitted"))
    member_job = str(name) == member or _names(member=member, text=str(job.get("strategy", "")))
    for step in _steps(job=job):
        if not _step_runs_member(member=member, step=step, member_job=member_job):
            continue
        guarded = _omission_condition(
            member=member, condition=step.get("if"), matrix="matrix."
        ) or _shell_guarded(member=member, step=step)
        if not guarded:
            return False
    return True


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
            if not (_names(member=member, text=str(job)) or str(name) == member):
                continue
            if not _job_omits_member(member=member, name=name, job=job):
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
