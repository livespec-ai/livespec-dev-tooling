"""Regression coverage for the signed server-side revert guidance."""

from __future__ import annotations

from pathlib import Path

from livespec_dev_tooling.checks._red_green_replay_protocol import RED_GREEN_REPLAY_PROTOCOL
from livespec_dev_tooling.checks._red_green_replay_revert import RANGE_MISSING_TRAILERS_HINT

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_shipped_guidance_prescribes_the_signed_create_commit_on_branch_restore() -> None:
    """A red-master operator receives the only server-side route this gate admits."""
    assert "one GraphQL `createCommitOnBranch` commit" in RANGE_MISSING_TRAILERS_HINT
    assert "every path changed by the reverted commits" in RANGE_MISSING_TRAILERS_HINT
    assert (
        "parent of the earliest reverted commit that landed on master"
        in RANGE_MISSING_TRAILERS_HINT
    )
    assert (
        "`This reverts commit <that commit's sha>.` on its own line" in RANGE_MISSING_TRAILERS_HINT
    )
    assert (
        "only when no master commit after the reverted commits changed any of those paths"
        in RANGE_MISSING_TRAILERS_HINT
    )
    assert "GitHub pull-request 'Revert' button" in RANGE_MISSING_TRAILERS_HINT
    assert "GraphQL `revertPullRequest` mutation (`gh pr revert`)" in RANGE_MISSING_TRAILERS_HINT
    assert "unsigned commits that this check refuses" in RANGE_MISSING_TRAILERS_HINT
    assert "createCommitOnBranch" in RED_GREEN_REPLAY_PROTOCOL

    for guidance_path in ("AGENTS.md", "CLAUDE.md"):
        guidance = (_REPOSITORY_ROOT / guidance_path).read_text(encoding="utf-8")
        assert "createCommitOnBranch" in guidance
        assert "Revert button" in guidance
        assert "revertPullRequest" in guidance
        assert "unsigned" in guidance
        assert "refused" in guidance
