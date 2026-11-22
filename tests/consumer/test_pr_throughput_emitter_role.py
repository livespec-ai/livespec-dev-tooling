"""Consumer-tier proof for the pr-throughput emitter's committed user unit.

The `pr_throughput_emitter` role (livespec-dev-tooling-h3b3ca) keeps the stopgap
emitter loop alive as a systemd user unit that restarts on failure, and has a
committed `absent` switch. These tests read the committed role, play and
inventory, because the live apply is a host action.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

__all__: list[str] = []

pytestmark = pytest.mark.consumer

_ANSIBLE = Path(__file__).resolve().parents[2] / "ansible"
_ROLE = _ANSIBLE / "roles" / "pr_throughput_emitter"


def _tasks() -> list[dict[str, object]]:
    return yaml.safe_load((_ROLE / "tasks" / "main.yml").read_text(encoding="utf-8"))


def _blocks() -> dict[str, list[dict[str, object]]]:
    return {str(t["when"]): t["block"] for t in _tasks() if "block" in t and "when" in t}


def test_the_unit_restarts_on_failure_runs_through_bash_and_is_wanted_by_default_target() -> None:
    unit = (_ROLE / "templates" / "pr-throughput-emit-loop.service.j2").read_text(encoding="utf-8")
    assert "Restart=on-failure" in unit
    assert "ExecStart=/bin/bash {{ pr_throughput_emitter_script }}" in unit
    assert "WantedBy=default.target" in unit


def test_the_role_installs_by_default_and_only_two_states_are_accepted() -> None:
    defaults = yaml.safe_load((_ROLE / "defaults" / "main.yml").read_text(encoding="utf-8"))
    assert defaults["pr_throughput_emitter_state"] == "present"
    guard = _tasks()[0]["ansible.builtin.assert"]["that"]
    assert guard == "pr_throughput_emitter_state in ['present', 'absent']"


def test_present_enables_and_starts_the_unit_in_the_user_scope() -> None:
    present = _blocks()["pr_throughput_emitter_state == 'present'"]
    arm = present[-1]["ansible.builtin.systemd_service"]
    assert arm["enabled"] is True
    assert arm["state"] == "started"
    assert arm["scope"] == "user"


def test_present_refuses_a_host_without_linger_and_stops_a_transient_copy() -> None:
    text = yaml.safe_dump(_blocks()["pr_throughput_emitter_state == 'present'"])
    assert "/var/lib/systemd/linger/" in text
    assert "FragmentPath" in text


def test_absent_stops_disables_removes_the_unit_and_reloads_the_user_manager() -> None:
    absent = _blocks()["pr_throughput_emitter_state == 'absent'"]
    stop = absent[0]["ansible.builtin.systemd_service"]
    assert stop["enabled"] is False
    assert stop["state"] == "stopped"
    assert stop["scope"] == "user"
    assert absent[1]["ansible.builtin.file"]["state"] == "absent"
    assert absent[2]["ansible.builtin.meta"] == "flush_handlers"


def test_the_play_selects_a_group_and_the_group_holds_the_emitter_host() -> None:
    play = yaml.safe_load((_ANSIBLE / "pr-throughput-emitter.yml").read_text(encoding="utf-8"))[0]
    assert play["hosts"] == "pr_throughput_emitter_hosts"
    inventory = yaml.safe_load((_ANSIBLE / "inventory" / "legacy.yml").read_text(encoding="utf-8"))
    group = inventory["all"]["children"]["pr_throughput_emitter_hosts"]
    assert list(group["hosts"]) == ["hetzner-xubuntu"]
