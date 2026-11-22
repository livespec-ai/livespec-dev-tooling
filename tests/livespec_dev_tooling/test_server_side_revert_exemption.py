"""Regression coverage for the server-side revert operator guidance."""

from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_EXEMPTION_GUIDE = _REPOSITORY_ROOT / "docs" / "server-side-revert-exemption.md"


def test_guide_distinguishes_measured_signed_and_unsigned_forge_routes() -> None:
    """OAuth createCommitOnBranch is signed; the listed alternatives are not."""
    guide = _EXEMPTION_GUIDE.read_text(encoding="utf-8")

    assert "createCommitOnBranch" in guide
    assert "gh OAuth user token" in guide
    assert "GitHub's web-flow signing key" in guide
    assert "GitHub App installation token" in guide
    assert "livespec-dev-tooling-2yne2h" in guide
    assert "revertPullRequest" in guide
    assert "gh pr revert" in guide
    assert "REST contents API" in guide
    assert "unsigned" in guide
