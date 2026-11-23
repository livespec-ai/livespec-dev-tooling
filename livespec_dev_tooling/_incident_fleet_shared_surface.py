"""Committed determinations of which shared-build surfaces may cite another adopter.

The audit, not an individual claim, owns this classification.  The configuration is
deliberately conservative: a surface remains non-shareable whenever its reader takes
an adopter-owned input.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from livespec_dev_tooling.incident_strict_json import IncidentJsonRefusalError, strict_json

__all__: list[str] = ["SharedSurfaceDetermination", "shared_surface_determination"]

_PATH = Path(__file__).resolve().parents[1] / "config" / "incident-fleet-shared-surfaces.json"


@dataclass(frozen=True, kw_only=True)
class SharedSurfaceDetermination:
    fully_determined: bool
    adopter_configuration: tuple[str, ...]


def _surfaces() -> dict[str, object]:
    """The committed surface table; empty when the configuration is unreadable."""
    try:
        document = cast("object", strict_json(text=_PATH.read_text(encoding="utf-8"), limit=None))
    except (OSError, ValueError, IncidentJsonRefusalError):
        return {}
    if not isinstance(document, dict):
        return {}
    entries = cast("dict[str, object]", document).get("surfaces")
    return cast("dict[str, object]", entries) if isinstance(entries, dict) else {}


def _determination(*, entry: object) -> SharedSurfaceDetermination | None:
    if not isinstance(entry, dict):
        return None
    row = cast("dict[str, object]", entry)
    fully_determined = row.get("fully_determined")
    inputs = row.get("adopter_configuration")
    if not isinstance(fully_determined, bool) or not isinstance(inputs, list):
        return None
    values = cast("list[object]", inputs)
    if not all(isinstance(value, str) and value for value in values):
        return None
    return SharedSurfaceDetermination(
        fully_determined=fully_determined,
        adopter_configuration=tuple(cast("list[str]", values)),
    )


def shared_surface_determination(*, surface: str) -> SharedSurfaceDetermination | None:
    """Read one released classification; malformed committed configuration is unusable."""
    return _determination(entry=_surfaces().get(surface))
