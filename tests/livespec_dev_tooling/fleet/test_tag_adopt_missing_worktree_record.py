"""A tag adopt materializes a record for a fresh linked worktree."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from returns.io import IOSuccess

from livespec_dev_tooling.budgeted_gh import GhRead
from livespec_dev_tooling.fleet._local_context import CommandOutcome, CommandResult
from livespec_dev_tooling.fleet._orchestrator_hold import ORCHESTRATOR_PLUGIN
from livespec_dev_tooling.fleet._tag_adopt import TagAdoptHost, tag_adopt

__all__: list[str] = []

_MARKET = "livespec-orchestrator-beads-fabro"
_REPO = "livespec-ai/livespec-orchestrator-beads-fabro"
_TAG = "v0.343.6"
_TAG_COMMIT = "e" * 40
_REF_COMMIT = "a" * 40
_REQUIRED = "skills/next/SKILL.md"


def _write(*, path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def test_tag_adopt_materializes_only_a_fresh_worktrees_record(*, tmp_path: Path) -> None:
    """A canary's first tag adopt must not need an unsafe session reconcile."""
    plugins_root = tmp_path / "home" / ".claude" / "plugins"
    primary = tmp_path / "primary"
    worktree = tmp_path / "primary-worktrees" / "canary"
    registry = plugins_root / "installed_plugins.json"
    primary_record = {
        "scope": "project",
        "projectPath": str(primary),
        "installPath": "/cache/primary",
        "gitCommitSha": _REF_COMMIT,
    }
    _write(
        path=registry,
        value={"version": 2, "plugins": {ORCHESTRATOR_PLUGIN: [primary_record]}},
    )
    _write(
        path=plugins_root / "known_marketplaces.json",
        value={
            _MARKET: {
                "source": {"source": "github", "repo": _REPO, "ref": "release"},
            }
        },
    )
    _write(
        path=worktree / ".claude" / "settings.json",
        value={
            "enabledPlugins": {ORCHESTRATOR_PLUGIN: True},
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "",
                        "hooks": [
                            {"type": "command", "command": "mise exec -- just ensure-plugins"}
                        ],
                    }
                ]
            },
        },
    )

    def run(*, args: list[str], cwd: Path | None = None) -> CommandOutcome:
        _ = cwd
        if args[0] == "git":
            return IOSuccess(
                CommandResult(
                    returncode=0,
                    stdout=(
                        f"{_TAG_COMMIT}\trefs/tags/{_TAG}\n" f"{_REF_COMMIT}\trefs/heads/release\n"
                    ),
                    stderr="",
                )
            )
        return IOSuccess(CommandResult(returncode=0, stdout="", stderr=""))

    def gh(*, args: list[str]) -> GhRead:
        if "/releases/tags/" in args[1]:
            return GhRead(
                returncode=0,
                stdout=json.dumps({"tag_name": _TAG, "draft": False}),
                stderr="",
            )
        return GhRead(returncode=0, stdout="ahead\n", stderr="")

    def run_env(*, args: list[str], cwd: Path, env: Mapping[str, str]) -> CommandOutcome:
        if args[:3] == ["claude", "plugin", "install"]:
            home = Path(env["HOME"])
            build = (
                home
                / ".claude"
                / "plugins"
                / "cache"
                / _MARKET
                / "livespec-orchestrator-beads-fabro"
                / _TAG_COMMIT[:12]
            )
            _write(path=build / "cache-manifest.json", value={"required_paths": [_REQUIRED]})
            _write(path=build / _REQUIRED, value="skill")
            _write(
                path=home / ".claude" / "plugins" / "installed_plugins.json",
                value={
                    "version": 2,
                    "plugins": {
                        ORCHESTRATOR_PLUGIN: [
                            {
                                "scope": "project",
                                "projectPath": str(cwd),
                                "installPath": str(build),
                                "gitCommitSha": _TAG_COMMIT,
                            }
                        ]
                    },
                },
            )
        return IOSuccess(CommandResult(returncode=0, stdout="", stderr=""))

    outcome = tag_adopt(
        clone=worktree,
        tag=_TAG,
        host=TagAdoptHost(
            run=run,
            gh=gh,
            run_env=run_env,
            base_env={"PATH": "/usr/bin", "HOME": "/host-home"},
            plugins_root=plugins_root,
            scratch_root=tmp_path / "scratch",
            read_text=lambda path: path.read_text(encoding="utf-8"),
            sleep=lambda _seconds: None,
            settle_seconds=0,
            now=lambda: "2026-11-21T15:00:00.000Z",
        ),
    )

    records = json.loads(registry.read_text(encoding="utf-8"))["plugins"][ORCHESTRATOR_PLUGIN]
    assert outcome.failure == ""
    assert records[0] == primary_record
    assert records[1]["projectPath"] == str(worktree)
    assert records[1]["gitCommitSha"] == _TAG_COMMIT
    assert str(worktree) in outcome.lines[0]
