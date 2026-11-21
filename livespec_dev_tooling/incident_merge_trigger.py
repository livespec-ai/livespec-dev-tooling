"""Start the incident-merge runner only for the observer's one green armed pull request.

The production observer role invokes this module from a root-owned systemd timer.
It accepts no pull-request argument: the number comes solely from the controller's
digest-verified arm record.  The runner repeats every merge-time check, so a state
change between this trigger's read and the runner's own read still fails closed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from livespec_dev_tooling._incident_app_installation import AppRefusal
from livespec_dev_tooling._incident_merge_bindings import (
    LedgerWriteError,
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
    repository_lock,
)
from livespec_dev_tooling.checks._effective_required_checks import ForgeReader
from livespec_dev_tooling.config import load_config
from livespec_dev_tooling.incident_merge_app import MergeForge
from livespec_dev_tooling.incident_merge_forge import (
    Green,
    IncidentForgeReadError,
    has_incident_label,
    required_checks_verdict,
)

__all__ = ["main", "run"]

DEFAULT_REPOSITORY = "livespec-ai/livespec-dev-tooling"
DEFAULT_STATE_DIR = Path("/var/lib/livespec-incident/receipts")


@dataclass(frozen=True, kw_only=True)
class _Arm:
    incident_id: str
    pr_number: int
    head_sha: str


def _parse(*, argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="incident_merge_trigger")
    _ = parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    _ = parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    _ = parser.add_argument("--project-root", type=Path, default=Path.cwd())
    _ = parser.add_argument("--credential", type=Path, default=DEFAULT_CREDENTIAL_PATH)
    _ = parser.add_argument("--unit-prefix", default="livespec-incident-merge")
    return parser.parse_args(list(argv))


def _read_arm(*, state_dir: Path, repository: str) -> _Arm | str:
    """Read one valid, current pre-merge arm, never a caller-selected pull request."""
    try:
        with repository_lock(directory=state_dir, repository=repository) as path:
            record = load_record(path=path)
            arm = read_observer_arm(record=record)
            invalidated = record.get("observer_arm_invalidated") is not None
    except (OSError, TypeError, ValueError):
        return "arm-unreadable"
    if arm is None or invalidated:
        return "arm-unbound"
    return _Arm(incident_id=arm.incident_item_id, pr_number=arm.pr_number, head_sha=arm.head_sha)


def _record(*, incident_id: str, reason: str, detail: str, pr_number: int) -> int:
    """Write the named refusal on the incident item, or name that recording failed."""
    try:
        ledger_recorder(run=run_text)(
            incident_id=incident_id,
            text="\n".join(
                (
                    "incident-merge-trigger: refused",
                    f"reason: {reason}",
                    f"detail: {detail}",
                    f"pull-request: {pr_number}",
                )
            ),
        )
    except LedgerWriteError:
        _ = sys.stdout.write("incident-merge-trigger-record-failed: LedgerWriteError\n")
        return 3
    _ = sys.stdout.write(f"incident-merge-trigger-refused: {reason}: {detail}\n")
    return 1


def _start(*, unit_prefix: str, pr_number: int) -> int:
    """Start exactly one parameterized unit without waiting for its merge result."""
    unit = f"{unit_prefix}@{pr_number}.service"
    done = subprocess.run(  # noqa: S603 -- unit is built from the observer arm's integer.
        ["/usr/bin/systemctl", "start", "--no-block", unit], check=False
    )
    if done.returncode:
        _ = sys.stdout.write(f"incident-merge-trigger-start-failed: {unit}\n")
        return 2
    _ = sys.stdout.write(f"incident-merge-trigger-started: {unit}\n")
    return 0


def run(  # noqa: PLR0911 -- every authorization fence is a distinct terminal refusal.
    *,
    argv: Sequence[str],
    owner_uid: int = 0,
    read_arm: Callable[..., _Arm | str] = _read_arm,
    connect: Callable[..., MergeForge | AppRefusal] = MergeForge.connect,
    make_reader: Callable[..., ForgeReader] = token_forge_reader,
    start: Callable[..., int] = _start,
) -> int:
    """Fence the timer to one armed, labelled, check-green expedited repair."""
    args = _parse(argv=argv)
    arm = read_arm(state_dir=args.state_dir, repository=args.repository)
    if isinstance(arm, str):
        _ = sys.stdout.write(f"incident-merge-trigger-refused: {arm}\n")
        return 1
    config = load_config(repo_root=args.project_root)
    credential = load_merge_credential(
        path=args.credential,
        owner_uid=owner_uid,
        merge_integration_id=config.incident_merge_integration_id,
        recovery_integration_id=config.recovery_bypass_integration_id,
    )
    if isinstance(credential, AppRefusal):
        return _record(
            incident_id=arm.incident_id,
            reason=credential.code,
            detail=credential.detail,
            pr_number=arm.pr_number,
        )
    forge = connect(repository=args.repository, credential=credential)
    if isinstance(forge, AppRefusal):
        return _record(
            incident_id=arm.incident_id,
            reason=forge.code,
            detail=forge.detail,
            pr_number=arm.pr_number,
        )
    reader = make_reader(token=forge.token)
    try:
        labelled = has_incident_label(forge=reader, repo=args.repository, pr_number=arm.pr_number)
        checks = required_checks_verdict(forge=reader, repo=args.repository, head_sha=arm.head_sha)
    except IncidentForgeReadError as error:
        return _record(
            incident_id=arm.incident_id,
            reason="forge-unreadable",
            detail=str(error),
            pr_number=arm.pr_number,
        )
    if not labelled:
        return _record(
            incident_id=arm.incident_id,
            reason="label-absent",
            detail="no expedited-incident-response label",
            pr_number=arm.pr_number,
        )
    if not isinstance(checks, Green):
        return _record(
            incident_id=arm.incident_id,
            reason="checks-not-green",
            detail=checks.reason,
            pr_number=arm.pr_number,
        )
    return start(unit_prefix=args.unit_prefix, pr_number=arm.pr_number)


def main() -> int:
    """Run the timer entry point with no caller-provided pull-request number."""
    return run(argv=sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
