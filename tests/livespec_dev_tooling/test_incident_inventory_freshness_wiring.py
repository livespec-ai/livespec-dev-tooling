"""The incident CI inventory freshness read is wired into the release path and a schedule.

Work-item livespec-dev-tooling-m4mm6g (from hhxmgv, plan expedited-incident-response-flag).
`scripts/just/check-incident-ci-inventory-freshness.sh` was merged with nothing invoking
it. Three committed workflow surfaces now carry it, and each is judged here against the
committed text and against a MUTATED copy that breaks exactly that rule, so a "the script
name appears somewhere" assertion cannot pass against wiring that is subtly wrong (a gate
step that runs on the tag-only push pass, a schedule that never fires, a watcher that
watches the wrong lane).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

__all__: list[str] = []

_WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
_SCRIPT = "scripts/just/check-incident-ci-inventory-freshness.sh"
_FRESHNESS_WORKFLOW = "incident-ci-inventory-freshness.yml"


def _load(*, text: str) -> dict[str, Any]:
    return cast("dict[str, Any]", yaml.safe_load(text))


def _triggers(*, workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML reads the bare key `on` as the boolean True.
    return cast("dict[str, Any]", workflow.get("on", workflow.get(True)))


def release_gate_findings(*, text: str) -> list[str]:
    """Findings for the release-please workflow's freshness gate step."""
    steps = _load(text=text)["jobs"]["release-please"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    gate = [step for step in steps if _SCRIPT in str(step.get("run", ""))]
    if len(gate) != 1:
        return [f"expected exactly one step running {_SCRIPT}, found {len(gate)}"]
    findings: list[str] = []
    if gate[0].get("if") != "github.event_name != 'push'":
        findings.append("the gate step must run only on the schedule and dispatch pass")
    if names.index(str(gate[0]["name"])) > names.index("Run release-please"):
        findings.append("the gate step must precede the release-please action")
    return findings


def scheduled_findings(*, text: str) -> list[str]:
    """Findings for the scheduled freshness workflow."""
    workflow = _load(text=text)
    findings: list[str] = []
    if not _triggers(workflow=workflow).get("schedule"):
        findings.append("the freshness workflow has no schedule")
    runs = [str(step.get("run", "")) for step in workflow["jobs"]["freshness"]["steps"]]
    if not any(_SCRIPT in run for run in runs):
        findings.append(f"the freshness job never runs {_SCRIPT}")
    return findings


def watcher_findings(*, text: str) -> list[str]:
    """Findings for the release-lane watcher shim."""
    workflow = _load(text=text)
    watch = workflow["jobs"]["watch"]
    findings: list[str] = []
    if not str(watch["uses"]).split("@")[0].endswith("/reusable-release-lane-watch.yml"):
        findings.append("the shim must call the shared reusable-release-lane-watch.yml")
    if watch["with"]["workflows"].split() != [_FRESHNESS_WORKFLOW]:
        findings.append(f"the watched set must be exactly {_FRESHNESS_WORKFLOW}")
    if watch["permissions"].get("issues") != "write":
        findings.append("the watcher needs issues: write to keep the durable issue")
    return findings


def _read(name: str) -> str:
    return (_WORKFLOWS / name).read_text(encoding="utf-8")


def test_the_release_pass_refuses_while_an_inventory_is_stale() -> None:
    assert release_gate_findings(text=_read("release-please.yml")) == []


@pytest.mark.parametrize(
    ("old", "new", "fragment"),
    [
        (
            "        if: github.event_name != 'push'\n        run: bash " + _SCRIPT,
            "        run: bash " + _SCRIPT,
            "only on the schedule",
        ),
        ("bash " + _SCRIPT, "echo skipped", "exactly one step"),
    ],
)
def test_a_release_gate_that_breaks_a_rule_is_found(old: str, new: str, fragment: str) -> None:
    mutated = _read("release-please.yml").replace(old, new)
    assert mutated != _read("release-please.yml")
    assert any(fragment in finding for finding in release_gate_findings(text=mutated))


def test_the_scheduled_workflow_runs_the_read_daily() -> None:
    assert scheduled_findings(text=_read(_FRESHNESS_WORKFLOW)) == []


def test_a_scheduled_workflow_without_a_schedule_or_the_read_is_found() -> None:
    text = _read(_FRESHNESS_WORKFLOW)
    unscheduled = text.replace(
        "  schedule:\n    - cron: '17 6 * * *'  # 06:17 UTC daily, ahead of release-lane-watch at 08:23\n",
        "",
    )
    assert any("no schedule" in f for f in scheduled_findings(text=unscheduled))
    no_read = text.replace("bash " + _SCRIPT, "echo skipped")
    assert any("never runs" in f for f in scheduled_findings(text=no_read))


def test_the_watcher_reports_the_freshness_lane_to_the_durable_issue() -> None:
    assert watcher_findings(text=_read("release-lane-watch.yml")) == []


def test_a_watcher_over_the_wrong_lane_is_found() -> None:
    mutated = _read("release-lane-watch.yml").replace(_FRESHNESS_WORKFLOW, "release-tag.yml")
    assert any("watched set" in f for f in watcher_findings(text=mutated))
