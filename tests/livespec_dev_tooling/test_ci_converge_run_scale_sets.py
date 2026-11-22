"""The scale-sets-only converge can be requested by variable (livespec-dev-tooling-jvgllz).

`ci_converge_unit_run_scale_sets` makes the role's placement task run
`converge-ci-stack.sh --scale-sets-only` through the normal committed apply with
no placement file change. These tests evaluate the task's own `when` conditions
against each combination of copy result, variable and check mode.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

__all__: list[str] = []

pytestmark = pytest.mark.integration

_ROLE = Path(__file__).resolve().parents[2] / "ansible" / "roles" / "ci_converge_unit"


def _step() -> dict[str, object]:
    tasks = yaml.safe_load((_ROLE / "tasks" / "placement.yml").read_text(encoding="utf-8"))
    commands = [t for t in tasks if "ansible.builtin.command" in t]
    assert len(commands) == 1
    return commands[0]


def _runs(*, copied: bool, run_requested: object, check_mode: bool) -> bool:
    """Evaluate the step's `when` list the way Ansible does, as Python."""
    when = _step()["when"]
    assert isinstance(when, list)
    truthy = {"true": True, "false": False}

    def _bool(value: object) -> bool:
        return truthy.get(str(value).lower(), bool(value))

    values = {
        "ci_converge_unit_placement_copied.changed": copied,
        "ci_converge_unit_run_scale_sets": _bool(run_requested),
        "ansible_check_mode": check_mode,
    }
    for condition in when:
        text = str(condition)
        for name, value in values.items():
            text = text.replace(f"({name} | bool)", str(value))
            text = text.replace(name, str(value))
        if not eval(text, {"__builtins__": {}}, {}):  # noqa: S307 - fixed expressions
            return False
    return True


def test_default_is_off() -> None:
    defaults = yaml.safe_load((_ROLE / "defaults" / "main.yml").read_text(encoding="utf-8"))
    assert defaults["ci_converge_unit_run_scale_sets"] is False


def test_variable_true_runs_the_step_with_no_placement_change() -> None:
    assert _runs(copied=False, run_requested=True, check_mode=False)


def test_variable_unset_runs_the_step_only_after_a_placement_change() -> None:
    assert not _runs(copied=False, run_requested=False, check_mode=False)
    assert _runs(copied=True, run_requested=False, check_mode=False)


def test_the_step_never_runs_under_check_mode() -> None:
    for copied in (True, False):
        for requested in (True, False):
            assert not _runs(copied=copied, run_requested=requested, check_mode=True)
