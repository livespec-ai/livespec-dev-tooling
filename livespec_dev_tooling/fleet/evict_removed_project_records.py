"""Remove stale project-scope plugin records after their worktree was removed."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from livespec_dev_tooling.fleet._adoption_lock import adoption_lock_path, holding_adoption_lock

__all__: list[str] = ["EvictionOutcome", "evict_records", "main"]


@dataclass(frozen=True, kw_only=True)
class EvictionOutcome:
    """The removed count, or why the registry could not be safely changed."""

    removed: int
    failure: str


def evict_records(  # noqa: PLR0911 — refusal reasons name distinct unsafe registry states.
    *, registry_path: Path, project_path: str
) -> EvictionOutcome:
    """Atomically remove every plugin record belonging to one already-removed project."""
    if Path(project_path).exists():
        return EvictionOutcome(
            removed=0, failure=f"refusing to evict records for existing project {project_path}"
        )
    try:
        text = registry_path.read_text(encoding="utf-8")
        registry = cast("object", json.loads(text))
    except (OSError, json.JSONDecodeError) as error:
        return EvictionOutcome(removed=0, failure=f"could not read {registry_path}: {error}")
    if not isinstance(registry, dict):
        return EvictionOutcome(removed=0, failure=f"{registry_path} has no plugin registry object")
    registry_mapping = cast("dict[str, object]", registry)
    if not isinstance(registry_mapping.get("plugins"), dict):
        return EvictionOutcome(removed=0, failure=f"{registry_path} has no plugin registry object")
    plugins = cast("dict[str, object]", registry_mapping["plugins"])
    removed = 0
    for plugin, entries in tuple(plugins.items()):
        if not isinstance(entries, list):
            continue
        entries = cast("list[object]", entries)
        kept = [
            entry for entry in entries if not _belongs_to(entry=entry, project_path=project_path)
        ]
        removed += len(entries) - len(kept)
        plugins[plugin] = kept
    if not removed:
        return EvictionOutcome(removed=0, failure="")
    temporary = registry_path.with_name(f"{registry_path.name}.livespec-evict.tmp")
    try:
        _ = temporary.write_text(f"{json.dumps(registry, indent=2)}\n", encoding="utf-8")
        _ = temporary.replace(registry_path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        return EvictionOutcome(removed=0, failure=f"could not write {registry_path}: {error}")
    return EvictionOutcome(removed=removed, failure="")


def _belongs_to(*, entry: object, project_path: str) -> bool:
    return (
        isinstance(entry, dict)
        and cast("dict[str, object]", entry).get("scope") == "project"
        and cast("dict[str, object]", entry).get("projectPath") == project_path
    )


def main() -> int:  # pragma: no cover
    """CLI entry point for a removed worktree's stale plugin records."""
    if len(sys.argv) != 2:  # noqa: PLR2004 — program name and removed worktree path.
        _ = sys.stderr.write(
            "usage: just evict-removed-project-plugin-records <removed-worktree>\n"
        )
        return 2
    project_path = sys.argv[1]
    home = Path.home()
    registry = home / ".claude" / "plugins" / "installed_plugins.json"

    def body() -> int:
        outcome = evict_records(registry_path=registry, project_path=project_path)
        if outcome.failure:
            _ = sys.stderr.write(f"evict-removed-project-plugin-records: {outcome.failure}\n")
            return 1
        message = f"evict-removed-project-plugin-records: {project_path}: removed {outcome.removed}"
        _ = sys.stdout.write(f"{message} project-scope install records\n")
        return 0

    def on_wait() -> None:
        _ = sys.stderr.write(
            "evict-removed-project-plugin-records: waiting for the host-wide adoption lock\n"
        )

    return holding_adoption_lock(
        path=adoption_lock_path(home=home),
        body=body,
        on_wait=on_wait,
    )
