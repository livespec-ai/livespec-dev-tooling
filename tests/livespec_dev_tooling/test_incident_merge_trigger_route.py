"""The observer role owns the committed route into the incident-merge runner.

The parameterized runner unit deliberately requires one pull-request number.  The
observer installation therefore needs its own released, timer-driven trigger rather
than a person starting ``livespec-incident-merge@<pr>`` as root on the host.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_ROLE = _ROOT / "ansible" / "roles" / "incident_observer"
_SERVICE = "livespec-incident-merge-trigger.service.j2"
_TIMER = "livespec-incident-merge-trigger.timer.j2"


def test_the_observer_role_installs_a_committed_timer_driven_merge_trigger() -> None:
    """The trigger is a root-owned observer route, never a hand-started runner.

    The trigger itself receives no pull-request argument: it must read the
    observer's fenced state and can therefore start only the one PR number the
    bound arm identifies.  A timer makes the committed installation, rather than
    an agent session, the caller that notices a newly green required-check set.
    """
    service = _ROLE / "templates" / _SERVICE
    timer = _ROLE / "templates" / _TIMER
    tasks = yaml.safe_load((_ROLE / "tasks" / "converge.yml").read_text(encoding="utf-8"))
    installs = [
        task
        for task in tasks
        if task.get("ansible.builtin.template", {}).get("src") in {_SERVICE, _TIMER}
    ]

    facts = [
        service.is_file(),
        timer.is_file(),
        "User=root" in service.read_text(encoding="utf-8") if service.is_file() else False,
        "-m livespec_dev_tooling.incident_merge_trigger" in service.read_text(encoding="utf-8")
        if service.is_file()
        else False,
        "WantedBy=timers.target" in timer.read_text(encoding="utf-8") if timer.is_file() else False,
        {task["ansible.builtin.template"]["src"] for task in installs} == {_SERVICE, _TIMER},
    ]

    assert all(facts)
