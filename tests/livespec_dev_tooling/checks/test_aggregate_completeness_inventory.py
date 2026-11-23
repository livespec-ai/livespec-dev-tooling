"""Regression coverage for the committed aggregate-check inventory test."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_AGGREGATE_COMPLETENESS_TEST = (
    _REPO_ROOT / "tests" / "livespec_dev_tooling" / "checks" / "test_aggregate_completeness.py"
)


def test_real_inventory_mirror_does_not_pin_a_member_count() -> None:
    """The mirror must follow its two committed inventory sources, not a third copy."""
    source = _AGGREGATE_COMPLETENESS_TEST.read_text(encoding="utf-8")

    assert "len(wired) ==" not in source, (
        "test_real_check_recipe_is_legacy_readable_exact_inventory_mirror must derive "
        "its expected inventory from justfile and check-targets.txt, not pin a member count"
    )
