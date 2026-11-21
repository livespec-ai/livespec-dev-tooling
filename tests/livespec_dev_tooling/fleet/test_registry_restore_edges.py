"""Edge cases of the registry restore, the record writer and the stale-record eviction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from returns.io import IOSuccess

from livespec_dev_tooling.fleet._ensure_plugin_artifacts import ArtifactOutcome
from livespec_dev_tooling.fleet._ensure_plugin_commands import (
    PluginCommandOutcome,
    PluginCommandResult,
)
from livespec_dev_tooling.fleet._orchestrator_hold import (
    ORCHESTRATOR_PLUGIN,
    restore_other_project_records,
)
from livespec_dev_tooling.fleet._registry_files import reconciled_registry
from livespec_dev_tooling.fleet._tag_adopt_record import write_record
from livespec_dev_tooling.fleet.ensure_plugins import ensure_report
from livespec_dev_tooling.fleet.evict_removed_project_records import evict_records

_ROOT = "/fleet/.worktrees/canary"
_OTHER = "/fleet/primary"


def _registry(*, records: object) -> str:
    return json.dumps({"plugins": {ORCHESTRATOR_PLUGIN: records}})


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (None, "{}"),
        ("{}", None),
        ("not json", "{}"),
        ("[]", "{}"),
        ('{"plugins": 1}', '{"plugins": {}}'),
        ('{"plugins": {}}', '{"plugins": {}}'),
        (
            _registry(records=[{"scope": "project", "projectPath": _OTHER}]),
            _registry(records=[{"scope": "project", "projectPath": _OTHER}]),
        ),
    ],
)
def test_a_registry_that_needs_no_restore_yields_none(
    *, before: str | None, after: str | None
) -> None:
    assert (
        restore_other_project_records(before_text=before, after_text=after, project_root=_ROOT)
        is None
    )


def test_reconciled_registry_leaves_an_unchanged_registry_alone() -> None:
    text = _registry(records=[{"scope": "project", "projectPath": _OTHER}])

    result = reconciled_registry(
        state_kind="absent",
        project_root=_ROOT,
        before_text=text,
        read_registry=lambda: text,
        write_registry=_refuse_any_write,
    )

    assert result == ("", text)


@pytest.mark.parametrize("registry", ["{}", '{"plugins": {}}'])
def test_write_record_creates_the_record_when_the_registry_lacks_the_plugin_table(
    *, tmp_path: Path, registry: str
) -> None:
    path = tmp_path / "installed_plugins.json"
    _ = path.write_text(registry, encoding="utf-8")

    _ = write_record(
        registry_path=path,
        clone=_ROOT,
        fields={"gitCommitSha": "a" * 40},
        read_text=lambda target: target.read_text(encoding="utf-8"),
        create_if_missing=True,
    )

    records = json.loads(path.read_text(encoding="utf-8"))["plugins"][ORCHESTRATOR_PLUGIN]
    assert records == [{"scope": "project", "projectPath": _ROOT, "gitCommitSha": "a" * 40}]


def test_evict_records_reports_an_unreadable_registry(*, tmp_path: Path) -> None:
    outcome = evict_records(
        registry_path=tmp_path / "absent.json", project_path=str(tmp_path / "x")
    )

    assert outcome.removed == 0
    assert "could not read" in outcome.failure


@pytest.mark.parametrize("registry", ["[]", '{"plugins": []}'])
def test_evict_records_refuses_a_registry_without_a_plugin_object(
    *, tmp_path: Path, registry: str
) -> None:
    path = tmp_path / "installed_plugins.json"
    _ = path.write_text(registry, encoding="utf-8")

    outcome = evict_records(registry_path=path, project_path=str(tmp_path / "gone"))

    assert "no plugin registry object" in outcome.failure


def test_evict_records_skips_non_list_entries_and_writes_nothing_when_none_match(
    *, tmp_path: Path
) -> None:
    path = tmp_path / "installed_plugins.json"
    text = json.dumps({"plugins": {"one@m": "scalar", "two@m": [{"scope": "user"}]}})
    _ = path.write_text(text, encoding="utf-8")

    outcome = evict_records(registry_path=path, project_path=str(tmp_path / "gone"))

    assert (outcome.removed, outcome.failure) == (0, "")
    assert path.read_text(encoding="utf-8") == text


def test_evict_records_reports_a_failed_write(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gone = str(tmp_path / "gone")
    path = tmp_path / "installed_plugins.json"
    _ = path.write_text(
        json.dumps({"plugins": {"one@m": [{"scope": "project", "projectPath": gone}]}}),
        encoding="utf-8",
    )

    def refuse_replace(self: Path, target: Path) -> Path:
        _ = (self, target)
        raise OSError("read-only filesystem")

    monkeypatch.setattr(Path, "replace", refuse_replace)

    outcome = evict_records(registry_path=path, project_path=gone)

    assert outcome.removed == 0
    assert "could not write" in outcome.failure
    assert not (tmp_path / "installed_plugins.json.livespec-evict.tmp").exists()


def _refuse_any_write(*, text: str) -> str:
    pytest.fail(f"nothing to restore, yet a write was attempted: {text}")


def _failing_write(*, text: str) -> str:
    _ = text
    return "could not restore"


def _ok(*, returncode: int = 0) -> PluginCommandOutcome:
    return IOSuccess(PluginCommandResult(returncode=returncode))


def _no_artifact_findings(*, install_path: str) -> ArtifactOutcome:
    _ = install_path
    return IOSuccess(())


def test_a_failed_registry_restore_is_reported_with_the_command_findings() -> None:
    primary = {"scope": "project", "projectPath": _OTHER, "gitCommitSha": "c" * 40}
    state = {"text": _registry(records=[primary])}

    def runner(*, args: tuple[str, ...]) -> PluginCommandOutcome:
        if args[2:3] == ("install",):
            state["text"] = _registry(
                records=[
                    {**primary, "gitCommitSha": "b" * 40},
                    {"scope": "project", "projectPath": _ROOT, "gitCommitSha": "b" * 40},
                ]
            )
        return _ok()

    report = ensure_report(
        settings_text=json.dumps({"enabledPlugins": {ORCHESTRATOR_PLUGIN: True}}),
        project_root=_ROOT,
        runner=runner,
        read_registry=lambda: state["text"],
        read_artifact=_no_artifact_findings,
        write_registry=_failing_write,
    )

    assert report.findings == ("could not restore",)


def test_a_failed_restore_after_the_cache_repair_is_reported(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    broken = home / ".claude" / "plugins" / "cache" / "broken"
    broken.mkdir(parents=True)
    _ = (broken / "plugin.json").write_text("{}", encoding="utf-8")
    _ = (broken / "cache-manifest.json").write_text(
        json.dumps({"required_paths": ["scripts/bin"]}), encoding="utf-8"
    )
    primary = {"scope": "project", "projectPath": _OTHER, "gitCommitSha": "c" * 40}
    state = {"text": _registry(records=[primary])}
    writes: list[str] = []

    def runner(*, args: tuple[str, ...]) -> PluginCommandOutcome:
        if args[2:3] == ("install",):
            state["text"] = _registry(
                records=[
                    {**primary, "gitCommitSha": "b" * 40},
                    {"scope": "project", "projectPath": _ROOT, "installPath": str(broken)},
                ]
            )
        return _ok()

    def write_registry(*, text: str) -> str:
        writes.append(text)
        if len(writes) == 1:
            state["text"] = text
            return ""
        return "second restore failed"

    report = ensure_report(
        settings_text=json.dumps({"enabledPlugins": {ORCHESTRATOR_PLUGIN: True}}),
        project_root=_ROOT,
        runner=runner,
        read_registry=lambda: state["text"],
        write_registry=write_registry,
    )

    assert report.findings == ("second restore failed",)
