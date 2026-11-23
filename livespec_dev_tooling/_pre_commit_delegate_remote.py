"""Remote-delegation outcome assembly for the pre-commit hook."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

# `returns` is VENDORED, not installed; a direct module invocation must make
# its sibling package importable before importing the Result implementation.
_VENDOR_DIR = Path(__file__).resolve().parent / "_vendor"
if str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

from returns.result import Failure  # noqa: E402  — vendor-path-aware import.

__all__: list[str] = ["run_remote"]


def run_remote(  # noqa: PLR0913 - the hook owns each independently patchable operation.
    *,
    repo_root: Path,
    tree_hash: str,
    check_suite: tuple[str, ...],
    build: Callable[..., Any],
    renderer: Callable[..., Path],
    runner: Callable[..., Any],
    run_gate: Callable[..., Any],
    replace_request: Callable[..., Any],
    staged_commit: Callable[..., str],
    refuses_declaration: Callable[..., bool],
    report: Callable[..., Any],
    repository_name: Callable[..., str | None],
    passed_state: str,
    failed_state: str,
    passed_outcome: str,
    failed_outcome: str,
    no_verdict: str,
    holds_tree: Callable[..., bool],
    authority_decision: Callable[..., Any],
    authority_members: Callable[..., Any],
    passed_members: Callable[..., Any],
    full_aggregate: Callable[..., bool],
    verdict_type: Callable[..., Any],
) -> Any:
    """Run one remote pre-commit gate and report its single final outcome."""
    built = build(
        repo_root=repo_root,
        renderer=renderer(repo_root=repo_root),
        runner=runner,
        tree_hash=tree_hash,
        check_suite=check_suite,
    )
    if isinstance(built, Failure):
        failure: Any = built.failure()
        refused = refuses_declaration(failure=failure)
        detail = str(failure.detail)
        return report(
            verdict=verdict_type(
                local=not refused,
                reason=(
                    "the commit is refused, not gated locally: unusable gate Job resources: "
                    f"{detail}"
                    if refused
                    else f"the gate Job could not be submitted: {detail}"
                ),
                tree_hash=tree_hash,
                exit_status=1 if refused else None,
            ),
            outcome=no_verdict,
            repository=repository_name(repo_root=repo_root),
        )
    request = built.unwrap()
    repository = request.mirror_url.rsplit("/", maxsplit=1)[-1].removesuffix(".git")
    source = staged_commit(repo_root=repo_root, tree_hash=tree_hash)
    if not source:
        return report(
            verdict=verdict_type(
                local=True,
                reason=(
                    "the staged tree could not be committed for the gate, so the aggregate "
                    "gates locally"
                ),
                tree_hash=tree_hash,
            ),
            outcome=no_verdict,
            repository=repository,
        )
    request = replace_request(request, source_ref=source, capture_output=True)
    remote = run_gate(request=request, runner=runner)
    if remote.tree_hash != tree_hash:
        return report(
            verdict=verdict_type(
                local=True,
                reason=(
                    "the gate Job did not return a verdict for the staged tree, so the aggregate "
                    f"gates locally: {remote.detail}"
                ),
                job_name=remote.job_name,
                tree_hash=tree_hash,
            ),
            outcome=no_verdict,
            repository=repository,
            remote=remote,
        )
    if remote.state == passed_state:
        host_unchanged = holds_tree(repo_root=repo_root, tree_hash=tree_hash)
        joined = authority_decision(
            verdict=remote,
            ran=authority_members(repo_root=repo_root, tree_hash=tree_hash, runner=runner),
        )
        return report(
            verdict=verdict_type(
                local=False,
                reason=joined.detail,
                job_name=joined.job_name,
                tree_hash=tree_hash,
                exit_status=0 if joined.state == passed_state else 1,
                output_checksum=joined.output_checksum,
                full_aggregate=full_aggregate(repo_root=repo_root, tree_hash=tree_hash),
                members_passed=(
                    None
                    if joined.member_verdicts is None
                    else passed_members(report=joined.member_verdicts)
                ),
                host_unchanged=host_unchanged,
            ),
            outcome=passed_outcome,
            repository=repository,
            remote=remote,
        )
    if remote.state == failed_state:
        return report(
            verdict=verdict_type(
                local=False,
                reason=remote.detail,
                job_name=remote.job_name,
                tree_hash=tree_hash,
                exit_status=1,
                output_checksum=remote.output_checksum,
            ),
            outcome=failed_outcome,
            repository=repository,
            remote=remote,
        )
    return report(
        verdict=verdict_type(
            local=True,
            reason=(
                "the gate Job reached no verdict for the staged tree, so the aggregate "
                "gates locally"
            ),
            job_name=remote.job_name,
            tree_hash=tree_hash,
        ),
        outcome=no_verdict,
        repository=repository,
        remote=remote,
    )
