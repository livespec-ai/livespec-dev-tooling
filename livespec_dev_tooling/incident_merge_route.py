"""Start the incident-merge runner for the ONE pull request the observer armed.

    python -I -m livespec_dev_tooling.incident_merge_route

The committed, fenced start for `livespec-incident-merge@<pr>` (livespec-dev-tooling-4r5rrv):
a root timer unit runs this once per interval, so the runner is no longer a hand start as
root. The route's only input is the observer's own arm record (`--state-dir`); it takes no
pull request number from anywhere else, so it can name exactly the armed pull request and
cannot start the runner without one.

It starts the runner only when ALL hold, each read now: the observer's arm is bound for the
repository, the armed pull request is open on the armed head, it carries the
`expedited-incident-response` label, and every context of the effective required-check set
concluded success on that head. Any other state starts nothing; a named refusal is recorded
once per (pull request, head, refusal) as a comment on the incident work item. A start is
recorded by a marker file under `--route-dir`, so the same armed head is started once. The
principal the runner calls re-reads every condition, so this route narrows when the runner
starts and never widens what it may merge.

Exit status: 0 started, or nothing to do; 1 a condition refused the start (named on stdout
and recorded); 2 the route could not read its inputs; 3 a record or the start itself failed.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

from livespec_dev_tooling._incident_app_installation import AppRefusal
from livespec_dev_tooling._incident_merge_bindings import (
    LedgerWriteError,
    TextRunner,
    ledger_recorder,
    run_text,
    token_forge_reader,
)
from livespec_dev_tooling._incident_merge_credential import (
    DEFAULT_CREDENTIAL_PATH,
    load_merge_credential,
)
from livespec_dev_tooling._incident_observer_store import (
    load_record,
    read_observer_arm,
    record_path,
)
from livespec_dev_tooling._incident_observer_types import ObserverArm
from livespec_dev_tooling.checks._effective_required_checks import ForgeReader
from livespec_dev_tooling.config import load_config
from livespec_dev_tooling.incident_merge_app import MergeForge
from livespec_dev_tooling.incident_merge_forge import (
    Green,
    IncidentForgeReadError,
    has_incident_label,
    required_checks_verdict,
)
from livespec_dev_tooling.incident_merge_runner import DEFAULT_REPOSITORY, DEFAULT_STATE_DIR
from livespec_dev_tooling.incident_strict_json import IncidentJsonRefusalError

__all__: list[str] = [
    "has_incident_label",
    "load_config",
    "load_merge_credential",
    "main",
    "required_checks_verdict",
    "run",
]

DEFAULT_ROUTE_DIR = Path("/var/lib/livespec-incident/route")
_STARTED, _REFUSED, _UNREADABLE, _FAILED = 0, 1, 2, 3
_HTTP_OK = 200
_NOT_OPEN = "not-open"


def _parse(*, argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="incident_merge_route")
    _ = parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    _ = parser.add_argument("--credential", type=Path, default=DEFAULT_CREDENTIAL_PATH)
    _ = parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    _ = parser.add_argument("--route-dir", type=Path, default=DEFAULT_ROUTE_DIR)
    _ = parser.add_argument("--project-root", type=Path, default=Path.cwd())
    return parser.parse_args(list(argv))


def _say(*, text: str) -> None:
    _ = sys.stdout.write(f"{text}\n")


def _marker(*, route_dir: Path, pr_number: int, head_sha: str, kind: str) -> Path:
    return route_dir / f"{pr_number}-{head_sha}.{kind}"


def _pull_state(*, forge: MergeForge, pr_number: int) -> tuple[str, str]:
    """(state, detail): `open` with the head sha, `not-open`, or `unreadable` with why."""
    status, body = forge.request(method="GET", path=f"pulls/{pr_number}")
    if status != _HTTP_OK or not isinstance(body, dict):
        return "unreadable", f"pull request read: HTTP {status}"
    pull = cast("dict[str, Any]", body)
    head = pull.get("head")
    sha = cast("dict[str, Any]", head).get("sha") if isinstance(head, dict) else None
    if not isinstance(sha, str):
        return "unreadable", "pull request carried no head sha"
    if pull.get("state") != "open" or pull.get("merged") is True:
        return _NOT_OPEN, sha
    return "open", sha


def _refusal(  # noqa: PLR0913 — one named condition with its identity.
    *,
    reason: str,
    detail: str,
    pr_number: int,
    head_sha: str,
    incident_id: str,
    route_dir: Path,
    run_text_command: TextRunner,
) -> int:
    """Name the refusal; record it once per (pull request, head, refusal) on the incident item."""
    _say(text=f"incident-merge-route-refused: {reason}: {detail}")
    digest = hashlib.sha256(f"{reason}\n{detail}".encode()).hexdigest()[:16]
    seen = _marker(route_dir=route_dir, pr_number=pr_number, head_sha=head_sha, kind=digest)
    if seen.exists():
        return _REFUSED
    text = "\n".join(
        [
            "incident-merge-route: refused",
            f"reason: {reason}",
            f"detail: {detail}",
            f"pull-request: {pr_number}",
            f"head-sha: {head_sha}",
        ]
    )
    try:
        ledger_recorder(run=run_text_command)(incident_id=incident_id, text=text)
    except LedgerWriteError as unrecorded:
        _say(text=f"incident-merge-route-record-failed: {unrecorded}")
        return _FAILED
    _ = seen.write_text("")
    return _REFUSED


def _start(*, pr_number: int, marker: Path, run_text_command: TextRunner) -> int:
    """Start `livespec-incident-merge@<pr_number>`; the marker is the once-per-head fence."""
    _ = marker.write_text("")
    code, detail = run_text_command(
        argv=["systemctl", "start", "--no-block", f"livespec-incident-merge@{pr_number}"]
    )
    if code != 0:
        marker.unlink()
        _say(text=f"incident-merge-route-start-failed: ({code}) {detail[:200]}")
        return _FAILED
    _say(text=f"incident-merge-route-started: pr {pr_number}")
    return _STARTED


def _read_arm(*, args: argparse.Namespace) -> ObserverArm | int:
    """The bound arm, or the exit status for why there is none (idle is a success)."""
    try:
        record = load_record(path=record_path(directory=args.state_dir, repository=args.repository))
        arm = read_observer_arm(record=record)
    except (OSError, ValueError, TypeError, IncidentJsonRefusalError) as unreadable:
        _say(text=f"incident-merge-route-unreadable: arm-unreadable: {type(unreadable).__name__}")
        return _UNREADABLE
    if arm is None:
        _say(text=f"incident-merge-route-idle: no-arm: no pre-merge arm for {args.repository}")
        return _STARTED
    return arm


def _unmet(
    *, forge: MergeForge, reader: ForgeReader, repository: str, arm: ObserverArm
) -> tuple[str, str] | None:
    """The first named condition the armed pull request fails, as (reason, detail), else None."""
    state, detail = _pull_state(forge=forge, pr_number=arm.pr_number)
    if state == "unreadable":
        return "forge-unreadable", detail
    if state == _NOT_OPEN:
        return _NOT_OPEN, ""
    if detail != arm.head_sha:
        return "arm-head-moved", f"the pull request head is {detail}"
    try:
        labelled = has_incident_label(forge=reader, repo=repository, pr_number=arm.pr_number)
    except IncidentForgeReadError as error:
        return "forge-unreadable", str(error)
    if not labelled:
        return "not-an-expedited-repair", "no expedited-incident-response label"
    checks = required_checks_verdict(forge=reader, repo=repository, head_sha=arm.head_sha)
    return None if isinstance(checks, Green) else ("checks-not-green", checks.reason)


def _connect(
    *, args: argparse.Namespace, owner_uid: int, connect: Callable[..., MergeForge | AppRefusal]
) -> MergeForge | int:
    """The merge App's forge access, or the exit status for why the route cannot read."""
    config = load_config(repo_root=args.project_root)
    credential = load_merge_credential(
        path=args.credential,
        owner_uid=owner_uid,
        merge_integration_id=config.incident_merge_integration_id,
        recovery_integration_id=config.recovery_bypass_integration_id,
    )
    if isinstance(credential, AppRefusal):
        _say(text=f"incident-merge-route-unreadable: {credential.code}: {credential.detail}")
        return _UNREADABLE
    forge = connect(repository=args.repository, credential=credential)
    if isinstance(forge, AppRefusal):
        _say(text=f"incident-merge-route-unreadable: {forge.code}: {forge.detail}")
        return _UNREADABLE
    return forge


def run(
    *,
    argv: Sequence[str],
    owner_uid: int = 0,
    connect: Callable[..., MergeForge | AppRefusal] = MergeForge.connect,
    make_reader: Callable[..., ForgeReader] = token_forge_reader,
    run_text_command: TextRunner = run_text,
) -> int:
    """Start the runner for the armed pull request, or say, by name, why not."""
    args = _parse(argv=argv)
    arm = _read_arm(args=args)
    if isinstance(arm, int):
        return arm
    forge = _connect(args=args, owner_uid=owner_uid, connect=connect)
    if isinstance(forge, int):
        return forge
    args.route_dir.mkdir(parents=True, exist_ok=True)
    started = _marker(
        route_dir=args.route_dir, pr_number=arm.pr_number, head_sha=arm.head_sha, kind="started"
    )
    if started.exists():
        _say(text=f"incident-merge-route-idle: already-started: pr {arm.pr_number}")
        return _STARTED
    reader = make_reader(token=forge.token)
    unmet = _unmet(forge=forge, reader=reader, repository=args.repository, arm=arm)
    if unmet is not None and unmet[0] == _NOT_OPEN:
        _say(text=f"incident-merge-route-idle: not-open: pr {arm.pr_number}")
        return _STARTED
    if unmet is not None:
        return _refusal(
            reason=unmet[0],
            detail=unmet[1],
            pr_number=arm.pr_number,
            head_sha=arm.head_sha,
            incident_id=arm.incident_item_id,
            route_dir=args.route_dir,
            run_text_command=run_text_command,
        )
    return _start(pr_number=arm.pr_number, marker=started, run_text_command=run_text_command)


def main() -> int:
    """Entry point: the pull request is never an argument, only the observer's arm names it."""
    return run(argv=sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
