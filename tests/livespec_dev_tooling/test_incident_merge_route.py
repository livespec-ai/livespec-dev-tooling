"""The incident-merge route starts the runner for one armed, green, labelled repair.

Work-item livespec-dev-tooling-4r5rrv (child of livespec-dev-tooling-bqnzcm). The runner
(`livespec-incident-merge@<pr>`) used to be started by hand as root. The route is the
committed, fenced start: a root timer unit runs it, it reads the observer's own arm record,
and it starts the runner for exactly the armed pull request, only when the pull request is a
labelled expedited repair on the armed head and every required check is green on that head.
Each refusal is named and recorded once on the incident work item.
"""

from __future__ import annotations

import hashlib
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import jinja2
import pytest
import yaml

import livespec_dev_tooling.incident_merge_route as route
from livespec_dev_tooling._incident_app_installation import AppRefusal
from livespec_dev_tooling._incident_observer_store import record_path, save_record
from livespec_dev_tooling.incident_merge_forge import Green, IncidentForgeReadError, NotGreen

# EXPEDITED_INCIDENT_RESPONSE flag: livespec-dev-tooling-4r5rrv

_ROOT = Path(__file__).resolve().parents[2]
_ROLE = _ROOT / "ansible" / "roles" / "incident_observer"
_REPO = "o/r"
_HEAD = "c" * 40
_PR = 7
_TOKEN = "installation-token-value"
_START = ["systemctl", "start", "--no-block", f"livespec-incident-merge@{_PR}"]


def _arm_record(*, pr_number: int = _PR) -> dict[str, object]:
    arm: dict[str, object] = {
        "repository": _REPO,
        "incident_item_id": "inc-1",
        "attempt_id": "attempt-1",
        "operation_id": "op-1",
        "owner": "owner-1",
        "phase": "repair",
        "base_sha": "b" * 40,
        "head_sha": _HEAD,
        "controller_release": "v1",
        "controller_revision": "r1",
        "authority_receipt": "ab",
        "generation": 3,
        "pr_number": pr_number,
        "required_jobs": ["check-lint"],
    }
    return {
        "observer_arm": arm,
        "observer_arm_id": hashlib.sha256(json.dumps(arm, sort_keys=True).encode()).hexdigest(),
    }


class _World:
    """One route world: every host dependency replaced, each answer chosen per case."""

    def __init__(self, *, monkeypatch, tmp_path: Path) -> None:
        self.state = tmp_path / "state"
        self.route_dir = tmp_path / "route"
        self.commands: list[list[str]] = []
        self.exit_codes: dict[str, int] = {}
        self.pull: tuple[int, object] = (200, self.pull_body())
        self.label: object = True
        self.verdict: object = Green(head_sha=_HEAD, contexts=frozenset({"check-lint"}))
        forge = SimpleNamespace(token=_TOKEN, request=lambda **_: self.pull)
        self.forge = forge
        config = SimpleNamespace(incident_merge_integration_id=1, recovery_bypass_integration_id=2)
        monkeypatch.setattr(route, "load_config", Mock(return_value=config))
        monkeypatch.setattr(
            route, "load_merge_credential", Mock(return_value=SimpleNamespace(app_id=1))
        )
        monkeypatch.setattr(route, "has_incident_label", self._has_label)
        monkeypatch.setattr(route, "required_checks_verdict", lambda **_: self.verdict)

    @staticmethod
    def pull_body(
        *, state: str = "open", head: str = _HEAD, merged: bool = False
    ) -> dict[str, object]:
        return {"state": state, "merged": merged, "head": {"sha": head}}

    def _has_label(self, **_: object) -> bool:
        if isinstance(self.label, Exception):
            raise self.label
        return bool(self.label)

    def runner(self, *, argv: list[str]) -> tuple[int, str]:
        self.commands.append(argv)
        key = "systemctl" if argv[0] == "systemctl" else "comment"
        return self.exit_codes.get(key, 0), "boom"

    def arm(self, *, pr_number: int = _PR) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        save_record(
            path=record_path(directory=self.state, repository=_REPO),
            record=_arm_record(pr_number=pr_number),
        )

    def go(self, *, connect=None) -> int:
        argv = [
            "--repository",
            _REPO,
            "--credential",
            "/nonexistent",
            "--state-dir",
            str(self.state),
            "--route-dir",
            str(self.route_dir),
            "--project-root",
            str(self.state),
        ]
        return route.run(
            argv=argv,
            owner_uid=0,
            connect=connect or (lambda **_: self.forge),
            make_reader=lambda **_: Mock(),
            run_text_command=self.runner,
        )

    def comments(self) -> list[str]:
        return [argv[-1] for argv in self.commands if argv[0] != "systemctl"]

    def starts(self) -> list[list[str]]:
        return [argv for argv in self.commands if argv[0] == "systemctl"]


@pytest.fixture
def world(monkeypatch, tmp_path) -> _World:
    return _World(monkeypatch=monkeypatch, tmp_path=tmp_path)


def test_an_armed_labelled_green_pull_request_starts_the_runner_for_exactly_that_number(world):
    world.arm()
    code = world.go()
    assert (code, world.starts(), world.comments()) == (0, [_START], [])


def test_the_route_starts_the_runner_once_per_armed_head(world):
    world.arm()
    first, second = world.go(), world.go()
    assert (first, second, world.starts()) == (0, 0, [_START])


def test_no_arm_starts_nothing_and_records_nothing(world, capsys):
    code = world.go()
    assert (code, world.commands, "no-arm" in capsys.readouterr().out) == (0, [], True)


def test_an_unreadable_arm_record_is_a_start_failure_not_a_start(world, capsys):
    world.state.mkdir(parents=True)
    _ = record_path(directory=world.state, repository=_REPO).write_text("{not json")
    code = world.go()
    assert (code, world.commands, "arm-unreadable" in capsys.readouterr().out) == (2, [], True)


def test_a_pull_request_without_the_label_is_refused_by_name_and_recorded_once(world):
    world.arm()
    world.label = False
    first, second = world.go(), world.go()
    facts = [
        (first, second) == (1, 1),
        world.starts() == [],
        len(world.comments()) == 1,
        "reason: not-an-expedited-repair" in world.comments()[0],
        f"pull-request: {_PR}" in world.comments()[0],
    ]
    assert all(facts)


def test_required_checks_not_green_on_the_head_is_refused_by_name(world):
    world.arm()
    world.verdict = NotGreen(head_sha=_HEAD, reason="check-lint is pending")
    code = world.go()
    facts = [
        code == 1,
        world.starts() == [],
        "reason: checks-not-green" in world.comments()[0],
        "check-lint is pending" in world.comments()[0],
    ]
    assert all(facts)


def test_a_head_that_moved_after_the_arm_is_refused_by_name(world):
    world.arm()
    world.pull = (200, world.pull_body(head="d" * 40))
    code = world.go()
    assert (code, world.starts(), "reason: arm-head-moved" in world.comments()[0]) == (1, [], True)


def test_an_unreadable_pull_request_or_label_is_refused_as_forge_unreadable(world):
    world.arm()
    world.pull = (500, {})
    first = world.go()
    world.pull = (200, world.pull_body())
    world.label = IncidentForgeReadError(path="p", detail="d")
    second = world.go()
    facts = [
        (first, second) == (1, 1),
        world.starts() == [],
        all("reason: forge-unreadable" in text for text in world.comments()),
        len(world.comments()) == 2,
    ]
    assert all(facts)


def test_a_pull_request_with_no_head_is_refused_as_forge_unreadable(world):
    world.arm()
    world.pull = (200, {"state": "open", "head": "x"})
    code = world.go()
    assert (code, "reason: forge-unreadable" in world.comments()[0]) == (1, True)


def test_a_closed_or_merged_pull_request_is_left_alone(world, capsys):
    world.arm()
    world.pull = (200, world.pull_body(state="closed"))
    closed = world.go()
    world.pull = (200, world.pull_body(merged=True))
    merged = world.go()
    assert (closed, merged, world.commands, "not-open" in capsys.readouterr().out) == (
        0,
        0,
        [],
        True,
    )


def test_a_credential_or_connection_refusal_starts_nothing(world, monkeypatch, capsys):
    world.arm()
    refusal = AppRefusal(code="credential-absent", detail="no file")
    monkeypatch.setattr(route, "load_merge_credential", Mock(return_value=refusal))
    first = world.go()
    monkeypatch.setattr(
        route, "load_merge_credential", Mock(return_value=SimpleNamespace(app_id=1))
    )
    second = world.go(connect=lambda **_: AppRefusal(code="app-denied", detail="no"))
    printed = capsys.readouterr().out
    assert (first, second, world.commands) == (2, 2, [])
    assert "credential-absent" in printed
    assert "app-denied" in printed


def test_a_failed_refusal_comment_is_reported_and_retried_on_the_next_run(world, capsys):
    world.arm()
    world.label = False
    world.exit_codes["comment"] = 1
    first = world.go()
    world.exit_codes["comment"] = 0
    second = world.go()
    facts = [
        first == 3,
        second == 1,
        len(world.comments()) == 2,
        "incident-merge-route-record-failed" in capsys.readouterr().out,
    ]
    assert all(facts)


def test_a_failed_start_is_reported_and_leaves_the_head_startable_again(world, capsys):
    world.arm()
    world.exit_codes["systemctl"] = 1
    first = world.go()
    world.exit_codes["systemctl"] = 0
    second = world.go()
    facts = [
        (first, second) == (3, 0),
        world.starts() == [_START, _START],
        "incident-merge-route-start-failed" in capsys.readouterr().out,
    ]
    assert all(facts)


def test_main_takes_its_arguments_from_the_command_line_only(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", ["route", "--state-dir", str(tmp_path / "absent")])
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as raised:
        _ = runpy.run_path(str(Path(route.__file__)), run_name="__main__")
    assert (raised.value.code, "no-arm" in capsys.readouterr().out) == (0, True)


# --- the committed install path ------------------------------------------------------------


def _render(*, name: str) -> str:
    environment = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    template = environment.from_string((_ROLE / "templates" / name).read_text())
    return template.render(
        ansible_managed="Ansible managed",
        incident_observer_merge_app_path="/etc/livespec-incident/merge-app.json",
        incident_observer_reference_dir="/var/lib/livespec-incident/reference",
        incident_observer_state_dir="/var/lib/livespec-incident/receipts",
        incident_observer_venv="/opt/livespec-incident/venv",
        incident_observer_merge_workdir="/declared/merge-workdir",
        incident_observer_merge_route_dir="/var/lib/livespec-incident/route",
        incident_observer_merge_route_interval="1min",
        incident_observer_merge_route_unit_name="livespec-incident-merge-route",
    )


def test_the_route_service_runs_the_route_as_root_with_no_pull_request_argument():
    unit = _render(name="livespec-incident-merge-route.service.j2")
    exec_lines = [line for line in unit.splitlines() if line.startswith("ExecStart=")]
    facts = [
        len(exec_lines) == 1,
        "-m livespec_dev_tooling.incident_merge_route " in exec_lines[0],
        " --pr " not in exec_lines[0],
        "--route-dir /var/lib/livespec-incident/route" in exec_lines[0],
        "Type=oneshot" in unit,
        "User=root" in unit,
        "NoNewPrivileges=yes" in unit,
        "ProtectSystem=strict" in unit,
        "ReadWritePaths=-/root/.config/op /var/lib/livespec-incident/route" in unit,
        "WorkingDirectory=/declared/merge-workdir" in unit,
    ]
    assert all(facts)


def test_the_route_timer_is_installed_and_kept_running_by_the_converge():
    timer = _render(name="livespec-incident-merge-route.timer.j2")
    tasks = yaml.safe_load((_ROLE / "tasks" / "converge.yml").read_text())
    installs = [t for t in tasks if "incident-merge route" in t.get("name", "")]
    sources = [item["src"] for task in installs for item in task.get("loop", []) if "src" in item]
    kept = [t for t in tasks if t.get("name", "").startswith("Keep the incident-merge route")]
    facts = [
        "OnUnitActiveSec=1min" in timer,
        "WantedBy=timers.target" in timer,
        "livespec-incident-merge-route.service.j2" in sources,
        "livespec-incident-merge-route.timer.j2" in sources,
        len(kept) == 1,
        kept[0]["ansible.builtin.systemd_service"]["enabled"] is True,
    ]
    assert all(facts)
