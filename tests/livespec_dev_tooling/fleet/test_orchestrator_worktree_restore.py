"""A fresh worktree reconcile never leaves Claude's primary-record rewrite behind."""

from __future__ import annotations

import json
from pathlib import Path

from returns.io import IOSuccess

from livespec_dev_tooling.fleet._ensure_plugin_artifacts import ArtifactOutcome
from livespec_dev_tooling.fleet._ensure_plugin_commands import (
    PluginCommandOutcome,
    PluginCommandResult,
)
from livespec_dev_tooling.fleet.ensure_plugins import ensure_report

_ORCHESTRATOR = "livespec-orchestrator-beads-fabro@livespec-orchestrator-beads-fabro"
_PRIMARY = "/fleet/primary"
_WORKTREE = "/fleet/.worktrees/canary"
_PRIMARY_BUILD = "c" * 40
_OFFERED_BUILD = "b" * 40


def test_absent_worktree_install_restores_the_primary_record_in_a_copied_registry(
    *, tmp_path: Path
) -> None:
    """The fixture registry is a copied HOME, never the operator's live registry."""
    registry = tmp_path / "home" / ".claude" / "plugins" / "installed_plugins.json"
    registry.parent.mkdir(parents=True)
    primary = {
        "scope": "project",
        "projectPath": _PRIMARY,
        "installPath": "/cache/primary",
        "gitCommitSha": _PRIMARY_BUILD,
    }
    _ = _write(registry, {"version": 2, "plugins": {_ORCHESTRATOR: [primary]}})

    def runner(*, args: tuple[str, ...]) -> PluginCommandOutcome:
        if args[2:] == ("install", _ORCHESTRATOR, "-s", "project"):
            _ = _write(
                registry,
                {
                    "version": 2,
                    "plugins": {
                        _ORCHESTRATOR: [
                            {**primary, "gitCommitSha": _OFFERED_BUILD},
                            {
                                "scope": "project",
                                "projectPath": _WORKTREE,
                                "installPath": "/cache/offered",
                                "gitCommitSha": _OFFERED_BUILD,
                            },
                        ]
                    },
                },
            )
        return IOSuccess(PluginCommandResult(returncode=0))

    def read_artifact(*, install_path: str) -> ArtifactOutcome:
        return _artifact_ok(install_path=install_path)

    report = ensure_report(
        settings_text=json.dumps({"enabledPlugins": {_ORCHESTRATOR: True}}),
        project_root=_WORKTREE,
        runner=runner,
        read_registry=lambda: registry.read_text(encoding="utf-8"),
        read_artifact=read_artifact,
        write_registry=lambda text: _write(registry, json.loads(text)),
    )

    records = json.loads(registry.read_text(encoding="utf-8"))["plugins"][_ORCHESTRATOR]
    assert report.findings == ()
    assert primary in records
    assert any(
        record["projectPath"] == _WORKTREE and record["gitCommitSha"] == _OFFERED_BUILD
        for record in records
    )


def _artifact_ok(*, install_path: str) -> ArtifactOutcome:
    _ = install_path
    return IOSuccess(())


def _write(path: Path, value: object) -> str:
    _ = path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return ""
