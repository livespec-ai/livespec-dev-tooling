"""Tests for eviction of plugin records left by a removed worktree."""

from __future__ import annotations

import json
from pathlib import Path

from livespec_dev_tooling.fleet.evict_removed_project_records import evict_records


def test_evict_records_removes_every_plugin_record_for_a_removed_worktree(
    *, tmp_path: Path
) -> None:
    registry = tmp_path / "home" / ".claude" / "plugins" / "installed_plugins.json"
    registry.parent.mkdir(parents=True)
    removed = str(tmp_path / "removed-worktree")
    primary = str(tmp_path / "primary")
    _ = registry.write_text(
        json.dumps(
            {
                "plugins": {
                    "one@market": [
                        {"scope": "project", "projectPath": removed},
                        {"scope": "project", "projectPath": primary},
                    ],
                    "two@market": [{"scope": "project", "projectPath": removed}],
                }
            }
        ),
        encoding="utf-8",
    )

    outcome = evict_records(registry_path=registry, project_path=removed)

    records = json.loads(registry.read_text(encoding="utf-8"))["plugins"]
    assert outcome.failure == ""
    assert outcome.removed == 2
    assert records["one@market"] == [{"scope": "project", "projectPath": primary}]
    assert records["two@market"] == []


def test_evict_records_refuses_a_project_path_that_still_exists(*, tmp_path: Path) -> None:
    project = tmp_path / "still-present"
    project.mkdir()

    outcome = evict_records(registry_path=tmp_path / "missing.json", project_path=str(project))

    assert "existing project" in outcome.failure
