"""Readiness findings from an adopter's committed incident CI workflow."""

from __future__ import annotations

import pytest

from livespec_dev_tooling import _incident_fleet_workflow as module
from livespec_dev_tooling.incident_ci_policy import CiTarget


def _not_applicable_inventory(*, repository: str) -> tuple[CiTarget, ...]:
    _ = repository
    return (CiTarget(name="check-slow", classification="not-applicable"),)


def test_workflow_findings_name_every_unsafe_observer_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hosted routing, missing observer inputs, and an unomitted member block readiness."""
    monkeypatch.setattr(
        module,
        "load_repository_inventory",
        _not_applicable_inventory,
    )
    findings = module.workflow_findings(
        repository="example/adopter",
        workflow="""jobs:
  incident-ci:
    runs-on: ubuntu-latest
  replay:
    runs-on: ubuntu-latest
    steps:
      - run: just check-red-green-replay
  checks:
    steps:
      - run: just check-slow
""",
    )
    assert any("incident-ci" in finding and "ubuntu-latest" in finding for finding in findings)
    assert any("replay" in finding and "ubuntu-latest" in finding for finding in findings)
    for input_name in (
        "LIVESPEC_INCIDENT_OBSERVER_URL",
        "LIVESPEC_INCIDENT_OBSERVER_CONNECT_ADDR",
        "LIVESPEC_INCIDENT_OBSERVER_QUERY_TOKEN",
    ):
        assert any(input_name in finding for finding in findings)
    assert any(
        "check-slow" in finding and "incident-policy omission" in finding for finding in findings
    )


def test_workflow_findings_accept_a_routed_replay_with_observer_inputs_and_omission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tailnet lane with each input and a policy report creates no workflow finding."""
    monkeypatch.setattr(
        module,
        "load_repository_inventory",
        _not_applicable_inventory,
    )
    findings = module.workflow_findings(
        repository="example/adopter",
        workflow="""jobs:
  incident-ci:
    runs-on: [self-hosted, k3s]
  replay:
    runs-on: [self-hosted, local-ci]
    steps:
      - run: just check-red-green-replay
        env:
          LIVESPEC_INCIDENT_OBSERVER_URL: url
          LIVESPEC_INCIDENT_OBSERVER_CONNECT_ADDR: address
          LIVESPEC_INCIDENT_OBSERVER_QUERY_TOKEN: token
  checks:
    steps:
      - run: echo omitted-by-incident-policy
      - run: just check-slow
""",
    )
    assert findings == ()


def test_workflow_findings_refuse_an_unavailable_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fleet audit cannot mark an adopter ready without its released inventory."""

    def unavailable(*, repository: str) -> tuple[CiTarget, ...]:
        _ = repository
        raise module.InventoryUndeclaredError

    monkeypatch.setattr(module, "load_repository_inventory", unavailable)
    findings = module.workflow_findings(
        repository="example/adopter",
        workflow="jobs:\n  incident-ci:\n    runs-on: [self-hosted, k3s]\n",
    )
    assert findings == ("example/adopter: released incident CI inventory is unavailable",)


def test_workflow_findings_refuse_an_unreadable_workflow() -> None:
    """No parsed jobs is a readiness blocker rather than a silent pass."""
    assert module.workflow_findings(repository="example/adopter", workflow=None) == (
        "example/adopter: default-branch ci.yml is unavailable or has no jobs",
    )
