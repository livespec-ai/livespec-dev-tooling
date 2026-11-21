"""Delegate an opted-in pre-commit aggregate to a staged-tree gate Job."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from livespec_dev_tooling._gate_host_authority import (
    host_authority_decision,
    run_host_authority_members,
)
from livespec_dev_tooling._gate_member_report import passed_members
from livespec_dev_tooling._gate_remote_assembly import (
    declared_gate_check_suite,
    refuses_declaration,
)
from livespec_dev_tooling._pre_commit_delegate_evidence import (
    host_holds_tree,
    record_delegated_evidence,
)
from livespec_dev_tooling._pre_commit_delegate_remote import run_remote
from livespec_dev_tooling._pre_push_evidence import clear_for_worktree
from livespec_dev_tooling.config import ConfigParseError, load_delegated_pre_commit
from livespec_dev_tooling.gate_credential import gates_kubeconfig_readable
from livespec_dev_tooling.gate_outcome_telemetry import (
    GATE_OUTCOME_NO_VERDICT,
    emit_gate_outcome,
)
from livespec_dev_tooling.gate_remote_delegate import gate_remote_request, resolve_renderer
from livespec_dev_tooling.gate_remote_invocation import default_gate_command_runner
from livespec_dev_tooling.gate_remote_verdict import (
    GATE_FAILED,
    GATE_PASSED,
    run_gated_push,
)
from livespec_dev_tooling.incident_gate_entry import IncidentEntrance

__all__: list[str] = ["PreCommitVerdict", "main", "run_pre_commit"]

_GATED_TREE_CHECK = "check-pre-commit-gated-tree"
_LOCAL_FALLBACK = 75


@dataclass(frozen=True, kw_only=True)
class PreCommitVerdict:
    """The pre-commit route and the staged-tree evidence it received."""

    local: bool
    reason: str
    job_name: str | None = None
    tree_hash: str | None = None
    exit_status: int | None = None
    output_checksum: str | None = None
    full_aggregate: bool = False
    members_passed: tuple[str, ...] | None = None
    host_unchanged: bool = False


def run_pre_commit(*, repo_root: Path) -> PreCommitVerdict:
    """Delegate only an eligible opted-in pre-commit aggregate, else gate locally."""
    try:
        enabled = load_delegated_pre_commit(repo_root=repo_root) is True
    except ConfigParseError:
        enabled = False
    if not enabled:
        return PreCommitVerdict(local=True, reason="delegated_pre_commit is not enabled")
    if not gates_kubeconfig_readable():
        return PreCommitVerdict(local=True, reason="gates kubeconfig is not readable")
    tree_hash = _staged_tree_hash(repo_root=repo_root)
    if not tree_hash:
        return _report_outcome(
            verdict=PreCommitVerdict(
                local=True,
                reason=(
                    "the staged tree could not be read, so the pre-commit aggregate gates locally"
                ),
            ),
            outcome=GATE_OUTCOME_NO_VERDICT,
            repository=_repository_name(repo_root=repo_root),
        )
    check_suite = _pre_commit_check_suite(repo_root=repo_root)
    if check_suite is None:
        return _report_outcome(
            verdict=PreCommitVerdict(
                local=True,
                reason=(
                    "the gate check suite could not be read, so the pre-commit aggregate "
                    "gates locally"
                ),
                tree_hash=tree_hash,
            ),
            outcome=GATE_OUTCOME_NO_VERDICT,
            repository=_repository_name(repo_root=repo_root),
        )
    return _run_remote(repo_root=repo_root, tree_hash=tree_hash, check_suite=check_suite)


def _staged_tree_hash(*, repo_root: Path) -> str:
    """Read the index tree the pre-commit aggregate must gate."""
    from returns.result import Failure

    written = default_gate_command_runner(argv=["git", "write-tree"], cwd=repo_root)
    if isinstance(written, Failure):
        return ""
    return written.unwrap().stdout.strip()


def _staged_tree_selects_full_aggregate(*, repo_root: Path, tree_hash: str) -> bool:
    """Say whether the hook ran the FULL aggregate for the gated tree, else False.

    A Job's exit status is the same for a full pass and for the doc-only or Red-leg
    subset, so the host classifies the staged tree itself: no staged `.py` selects the
    doc-only subset, and exactly one staged `tests/*.py` with no staged
    `livespec_dev_tooling/*.py` selects the Red leg, whatever other `.py` files are
    staged. Anything unreadable answers False, because evidence must never be claimed
    for a run that cannot be shown to be full.
    """
    from returns.result import Failure

    listed = default_gate_command_runner(
        argv=["git", "diff", "-z", "--name-only", "--diff-filter=AM", "HEAD", tree_hash],
        cwd=repo_root,
    )
    if isinstance(listed, Failure) or listed.unwrap().returncode != 0:
        return False
    staged_py = [name for name in listed.unwrap().stdout.split("\0") if name.endswith(".py")]
    if not staged_py:
        return False
    staged_tests = [name for name in staged_py if name.startswith("tests/")]
    staged_impl = [name for name in staged_py if name.startswith("livespec_dev_tooling/")]
    return not (len(staged_tests) == 1 and not staged_impl)


def _staged_commit(*, repo_root: Path, tree_hash: str) -> str:
    """Wrap the index tree in a commit object the gate client can publish."""
    from returns.result import Failure

    parents = ("HEAD",)
    marker = default_gate_command_runner(
        argv=["git", "rev-parse", "--git-path", "MERGE_HEAD"], cwd=repo_root
    )
    if not isinstance(marker, Failure) and marker.unwrap().returncode == 0:
        merge_head_path = repo_root / marker.unwrap().stdout.strip()
        if merge_head_path.is_file():
            parents += tuple(merge_head_path.read_text(encoding="utf-8").split())
    argv = [
        "git",
        "-c",
        "user.name=livespec-pre-commit",
        "-c",
        "user.email=pre-commit@livespec.invalid",
        "commit-tree",
        tree_hash,
    ]
    for parent in parents:
        argv.extend(["-p", parent])
    argv.append("-mpre-commit aggregate of the staged tree")
    committed = default_gate_command_runner(argv=argv, cwd=repo_root)
    if isinstance(committed, Failure):
        return ""
    return committed.unwrap().stdout.strip()


def _pre_commit_check_suite(*, repo_root: Path) -> tuple[str, ...] | None:
    """Keep the declared bootstrap while substituting the staged-tree aggregate."""
    from returns.result import Failure

    declared = declared_gate_check_suite(repo_root=repo_root)
    if isinstance(declared, Failure):
        return None
    return (*declared.unwrap()[:-1], _GATED_TREE_CHECK)


def _repository_name(*, repo_root: Path) -> str | None:
    """Name the repository whose delegated pre-commit run was selected.

    The hook has already been invoked for this checkout when it gets this far,
    so its root name is known even if assembly fails before a gate request can
    determine the mirror URL.  Empty names are omitted like every other
    undetermined telemetry attribute.
    """
    return repo_root.name or None


def _report_outcome(
    *,
    verdict: PreCommitVerdict,
    outcome: str,
    repository: str | None,
) -> PreCommitVerdict:
    """Best-effort report exactly one selected pre-commit delegation outcome."""
    emit_gate_outcome(
        outcome=outcome,
        repository=repository,
        tree_hash=verdict.tree_hash,
        job_name=verdict.job_name,
        stage="pre-commit",
    )
    return verdict


def _run_remote(
    *, repo_root: Path, tree_hash: str, check_suite: tuple[str, ...]
) -> PreCommitVerdict:
    """Run the aggregate remotely and accept only a matching staged-tree verdict."""
    return run_remote(
        repo_root=repo_root,
        tree_hash=tree_hash,
        check_suite=check_suite,
        build=gate_remote_request,
        renderer=resolve_renderer,
        runner=default_gate_command_runner,
        run_gate=run_gated_push,
        replace_request=replace,
        staged_commit=_staged_commit,
        refuses_declaration=refuses_declaration,
        report=_report_outcome,
        repository_name=_repository_name,
        passed_state=GATE_PASSED,
        failed_state=GATE_FAILED,
        passed_outcome="passed",
        failed_outcome="failed-tree",
        no_verdict=GATE_OUTCOME_NO_VERDICT,
        holds_tree=host_holds_tree,
        authority_decision=host_authority_decision,
        authority_members=run_host_authority_members,
        passed_members=passed_members,
        full_aggregate=_staged_tree_selects_full_aggregate,
        verdict_type=PreCommitVerdict,
    )


@IncidentEntrance(surface="pre-commit-delegate")
def main() -> int:
    """Run the selected route and report whether the shell must fall back locally."""
    import structlog

    parser = argparse.ArgumentParser(description="Delegate an opted-in pre-commit aggregate.")
    _ = parser.add_argument("command", choices=["run"])
    _ = parser.parse_args()
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )
    clear_for_worktree(cwd=Path.cwd())
    verdict = run_pre_commit(repo_root=Path.cwd())
    log = structlog.get_logger("pre_commit_delegate")
    if verdict.local:
        if verdict.reason != "delegated_pre_commit is not enabled":
            log.warning(
                "GATED_LOCALLY",
                reason=verdict.reason,
                job_name=verdict.job_name,
                tree_hash=verdict.tree_hash,
            )
        return _LOCAL_FALLBACK
    log.info(
        "delegated pre-commit aggregate completed",
        job_name=verdict.job_name,
        tree_hash=verdict.tree_hash,
        exit_status=verdict.exit_status,
        output_checksum=verdict.output_checksum,
        reason=verdict.reason,
    )
    record_delegated_evidence(cwd=Path.cwd(), log=log, verdict=verdict)
    return 1 if verdict.exit_status is None else verdict.exit_status


if __name__ == "__main__":
    raise SystemExit(main())
