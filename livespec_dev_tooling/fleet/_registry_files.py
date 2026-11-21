"""Registry seams and the post-command restore of other projects' orchestrator records.

Split out of `ensure_plugins` so that module stays under the file-LLOC hard
ceiling: the Protocols, the on-disk readers and writer, and the one reconcile
step that puts another project's record back after a fresh worktree's
project-scope install rewrote it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from livespec_dev_tooling.fleet._orchestrator_hold import restore_other_project_records

__all__: list[str] = [
    "RegistryReader",
    "RegistryWriter",
    "read_installed_registry",
    "read_marketplace_registry",
    "reconciled_registry",
    "write_installed_registry",
]


class RegistryReader(Protocol):
    """Callable seam reading the installed-plugins registry, or None if absent."""

    def __call__(self) -> str | None: ...


class RegistryWriter(Protocol):
    """Callable seam persisting the installed-plugin registry after a repair."""

    def __call__(self, *, text: str) -> str: ...


def read_installed_registry() -> str | None:  # pragma: no cover
    """The Claude installed-plugins registry text, or None when absent."""
    path = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def write_installed_registry(*, text: str) -> str:  # pragma: no cover
    """Atomically persist the repaired registry, or render the write failure."""
    path = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    temporary = path.with_name(f"{path.name}.livespec-ensure.tmp")
    try:
        _ = temporary.write_text(text, encoding="utf-8")
        _ = temporary.replace(path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        return f"could not restore other project orchestrator records: {error}"
    return ""


def read_marketplace_registry() -> str | None:  # pragma: no cover
    path = Path.home() / ".claude/plugins/known_marketplaces.json"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def reconciled_registry(
    *,
    state_kind: str,
    project_root: str,
    before_text: str | None,
    read_registry: RegistryReader,
    write_registry: RegistryWriter | None,
) -> tuple[str, str | None]:
    """Re-read the registry after the commands, restoring other projects' records.

    The restore runs only for an absent record with a writer supplied, and the
    registry is read again only after a restore was written.
    """
    registry_text = read_registry()
    if state_kind != "absent" or write_registry is None:
        return "", registry_text
    restored = restore_other_project_records(
        before_text=before_text, after_text=registry_text, project_root=project_root
    )
    if restored is None:
        return "", registry_text
    finding = write_registry(text=restored)
    return finding, registry_text if finding else read_registry()
