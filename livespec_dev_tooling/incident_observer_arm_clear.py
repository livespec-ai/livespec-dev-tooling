"""Clear a pre-merge observer arm whose incident chain was retired.

``/invalidate-ci`` needs the canonical current reader to verify the chain, so it
refuses an arm whose chain moved on. This route is the one sanctioned clear for
that case: the operator names the arm, who they are and why. It drops only the
retained UNBOUND arm, never one whose commit landed on the target branch, so it
cannot bypass a real repayment obligation. Afterwards the record holds no arm,
so the next incident's arm needs no compare-and-swap naming the cleared one.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, cast

from livespec_dev_tooling._incident_observer_store import (
    load_record,
    read_observer_arm,
    repository_lock,
    save_record,
)
from livespec_dev_tooling._incident_observer_types import ObserverArm
from livespec_dev_tooling.incident_controller_installation import ControllerInstallation
from livespec_dev_tooling.incident_git import run_git

__all__: list[str] = ["ObserverArmClear"]

# EXPEDITED_INCIDENT_RESPONSE flag: livespec-dev-tooling-s7yiut
_FIELDS = frozenset({"repository", "arm_id", "operation_id", "operator", "reason"})
_HISTORY = "arm_clears"


@dataclass(frozen=True, kw_only=True)
class ObserverArmClear:
    """Drop one retained unbound arm by operator request, keeping an immutable receipt."""

    installation: ControllerInstallation
    landed: Callable[[ObserverArm], bool | None] | None = None

    def execute(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self.installation
        if not _valid_request(payload=payload) or payload["repository"] != settings.repository:
            return _refused(reason="invalid exact arm clear request")
        with repository_lock(directory=settings.state, repository=settings.repository) as path:
            record = load_record(path=path)
            history = cast("dict[str, dict[str, Any]]", record.get(_HISTORY, {}))
            earlier = history.get(payload["operation_id"])
            if earlier is not None:
                if earlier["request"] != payload:
                    return _refused(reason="arm clear operation conflicts with immutable request")
                return cast("dict[str, Any]", earlier["result"])
            arm = read_observer_arm(record=record)
            if arm is None or record.get("observer_arm_id") != payload["arm_id"]:
                return _refused(reason="retained arm named by this request is unavailable")
            refusal = self._landed_refusal(record=record, arm=arm)
            if refusal is not None:
                return _refused(reason=refusal)
            result = _result(request=payload)
            record[_HISTORY] = {
                **history,
                payload["operation_id"]: {
                    "request": payload,
                    "result": result,
                    "cleared_arm": asdict(arm) | {"authority_receipt": arm.authority_receipt.hex()},
                    "cleared_at": datetime.now(tz=timezone.utc).isoformat(),
                },
            }
            record.update(
                observer_arm_id=None,
                observer_arm=None,
                observer_arm_bound=False,
                observer_arm_invalidated=None,
                registration=None,
            )
            save_record(path=path, record=record)
        return result

    def _landed_refusal(self, *, record: dict[str, object], arm: ObserverArm) -> str | None:
        settings = self.installation
        named = f"incident {arm.incident_item_id} commit {arm.head_sha}"
        if record.get("observer_arm_bound"):
            return f"{named} is bound to its master run; its repayment obligation stands"
        landed = (
            self.landed(arm)
            if self.landed is not None
            else _head_on_target(
                repo=settings.repo, target_branch=settings.target_branch, head=arm.head_sha
            )
        )
        if landed is None:
            return f"cannot establish whether {named} landed on {settings.target_branch}"
        if landed:
            return f"{named} landed on {settings.target_branch}; the arm cannot be cleared"
        return None


def _head_on_target(*, repo: Any, target_branch: str, head: str) -> bool | None:
    """True when `head` is an ancestor of the target branch, False when not, None when unknown."""
    done = run_git(
        repo=repo,
        args=("merge-base", "--is-ancestor", head, f"refs/remotes/origin/{target_branch}"),
        check=False,
    )
    return {0: True, 1: False}.get(done.returncode)


def _valid_request(*, payload: dict[str, Any]) -> bool:
    return (
        frozenset(payload) == _FIELDS
        and all(isinstance(payload[name], str) and payload[name] for name in _FIELDS)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}", payload["operation_id"]) is not None
    )


def _result(*, request: dict[str, Any]) -> dict[str, Any]:
    digest = hashlib.sha256(
        b"incident-arm-clear-v1\0"
        + json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema": 1,
        "status": "cleared",
        "receipt": digest,
        "cleared_arm_id": request["arm_id"],
        "operator": request["operator"],
        "reason": request["reason"],
        "authorizes_current_effects": False,
    }


def _refused(*, reason: str) -> dict[str, Any]:
    return {"schema": 1, "status": "refused", "reason": reason}
