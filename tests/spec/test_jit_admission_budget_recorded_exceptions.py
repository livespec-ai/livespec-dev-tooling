"""Recorded exception safeguards for the Adaptive JIT runner admission budget.

`DERIVATION.md` is the source of truth for ceilings that depart from
``max(2 x nominalQuota, 6)``.  Every such row must carry the check that
accepts the departure and the switch that undoes it, so a later configuration
edit cannot leave a ceiling outside the normal bound without an operating
criterion for retaining or reverting it.
"""

from __future__ import annotations

from pathlib import Path

__all__: list[str] = []

_DERIVATION = (
    Path(__file__).resolve().parents[2] / "ci-runner" / "k3s" / "phase2" / "kueue" / "DERIVATION.md"
)
_EXCEPTIONS_HEADING = "### Recorded exceptions to the rule"
_ACCEPTANCE_CHECK = "Acceptance check"
_KILL_SWITCH = "Kill switch"


def _exception_rows() -> list[dict[str, str]]:
    """Read the recorded-exceptions table without maintaining a test-side copy."""
    section = _DERIVATION.read_text(encoding="utf-8").split(_EXCEPTIONS_HEADING, 1)[1]
    lines = section.splitlines()
    table_start = next(index for index, line in enumerate(lines) if line.startswith("|"))
    table = []
    for line in lines[table_start:]:
        if not line.startswith("|"):
            break
        table.append(line)
    headers = [cell.strip().strip("`") for cell in table[0].strip("|").split("|")]
    return [
        dict(
            zip(
                headers,
                (cell.strip().strip("`") for cell in line.strip("|").split("|")),
                strict=False,
            )
        )
        for line in table[2:]
    ]


def test_recorded_exception_rows_name_an_acceptance_check_and_kill_switch() -> None:
    """Every departing ceiling has an explicit operating check and reversal path."""
    missing = [
        f"{row['Repository']}: maxRunners={row['maxRunners'].strip('*')}"
        for row in _exception_rows()
        if not row.get(_ACCEPTANCE_CHECK, "").strip() or not row.get(_KILL_SWITCH, "").strip()
    ]
    assert not missing, (
        "each recorded ceiling exception must name its acceptance check and kill switch; "
        f"missing={missing}"
    )
