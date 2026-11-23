"""Build the hookless git prefix for the delegated gate's internal mirror."""

from __future__ import annotations

__all__: list[str] = ["mirror_push"]


def mirror_push() -> list[str]:
    """Return the internal git push prefix without re-entering pre-push hooks."""
    return ["git", "-c", "core.hooksPath=/dev/null", "push"]
