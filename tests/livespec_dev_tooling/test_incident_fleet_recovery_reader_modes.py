"""The recovery authorization counts only the always-bypass App, not the incident-merge actor.

SPECIFICATION/contracts.md (the branch-protection ruleset bypass rule) lets a guarded ruleset
carry the recovery Integration with `bypass_mode` always AND, when the consumer commits an
`incident_merge_integration_id`, that second Integration with `bypass_mode` pull_request. The
reader must read the sole always-bypass App through that permitted second actor.
"""

from __future__ import annotations

import json

from livespec_dev_tooling._incident_fleet_recovery_reader import read_recovery_authorization
from livespec_dev_tooling.budgeted_gh import GhRead

__all__: list[str] = []

CONTROLLER = "v1.231.2@" + "4" * 40
BASE = "repos/example/tooling/rulesets"
ALWAYS = {"actor_id": 5761967, "actor_type": "Integration", "bypass_mode": "always"}
MERGE = {"actor_id": 5812830, "actor_type": "Integration", "bypass_mode": "pull_request"}


def _ok(document: object) -> GhRead:
    return GhRead(returncode=0, stdout=json.dumps(document), stderr="")


def _read(*, actors: list[object]) -> str | None:
    ruleset = {
        "id": 7,
        "enforcement": "active",
        "target": "branch",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}},
        "bypass_actors": actors,
    }
    answers = {
        "repos/example/tooling": _ok({"default_branch": "master"}),
        BASE: _ok([ruleset]),
        f"{BASE}/7": _ok(ruleset),
    }

    def read_forge(*, args: list[str]) -> GhRead:
        return answers.get(args[1], GhRead(returncode=1, stdout="", stderr="HTTP 404"))

    return read_recovery_authorization(
        repository="example/tooling", controller=CONTROLLER, read_forge=read_forge
    )


def test_the_permitted_pull_request_actor_does_not_hide_the_sole_always_bypass_app() -> None:
    assert _read(actors=[ALWAYS, MERGE]) == f"{CONTROLLER}+bypass-app-5761967"
