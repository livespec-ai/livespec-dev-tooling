"""Derive gate-stage measurements from Kubernetes Job timestamps."""

from __future__ import annotations

from datetime import datetime

__all__: list[str] = ["gate_timing_seconds"]


def gate_timing_seconds(
    *, created_at: str | None, admitted_at: str | None, terminal_at: str | None
) -> tuple[float | None, float | None]:
    """Return Job queue and run intervals, omitting unreadable or negative values."""
    return (
        _seconds_between(earlier=created_at, later=admitted_at),
        _seconds_between(earlier=admitted_at, later=terminal_at),
    )


def _seconds_between(*, earlier: str | None, later: str | None) -> float | None:
    if not earlier or not later:
        return None
    try:
        seconds = (
            datetime.fromisoformat(later.replace("Z", "+00:00"))
            - datetime.fromisoformat(earlier.replace("Z", "+00:00"))
        ).total_seconds()
    except ValueError:
        return None
    return seconds if seconds >= 0 else None
