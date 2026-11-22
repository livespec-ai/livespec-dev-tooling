"""CI priority record producer tests."""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from livespec_dev_tooling.ci_priority_record import (
    PriorityRecordError,
    _jsonc_text,
    _manifest,
    _matching_generated_at,
    _repositories,
    _run,
    build_record,
    main,
)
from livespec_dev_tooling.radar.radar import RadarEntry


def test_record_bands_open_plan_children_and_explicit_item_deterministically() -> None:
    """The producer joins the canonical radar to the list-work-items projection."""
    radar = (
        RadarEntry(
            kind="plan", tenant="tenant", id="plan", words="", said_at=date.today(), blocked_by=()
        ),
        RadarEntry(
            kind="item", tenant="tenant", id="item", words="", said_at=date.today(), blocked_by=()
        ),
        RadarEntry(
            kind="item", tenant="tenant", id="done", words="", said_at=date.today(), blocked_by=()
        ),
        RadarEntry(
            kind="item", tenant="tenant", id="absent", words="", said_at=date.today(), blocked_by=()
        ),
    )
    projection = [
        {"tenant": "tenant", "id": "done", "status": "closed", "parent": None},
        {"tenant": "tenant", "id": "plan.dotted", "status": "ready", "parent": None},
        {"tenant": "tenant", "id": "edge-child", "status": "active", "parent": "plan"},
        {"tenant": "tenant", "id": "closed", "status": "closed", "parent": "plan"},
        {"tenant": "tenant", "id": "item", "status": "ready", "parent": None},
    ]

    record = build_record(
        projection=projection,
        thresholds={"high": 1, "medium": 4},
        radar_commit="radar-sha",
        generated_at="2026-11-22T00:00:00Z",
        radar=radar,
    )

    assert record == {
        "schema": 1,
        "generated_at": "2026-11-22T00:00:00Z",
        "radar_commit": "radar-sha",
        "items": {"edge-child": "high", "item": "medium", "plan.dotted": "high"},
        "default": "low",
    }


def test_unchanged_record_reuses_its_timestamp(monkeypatch: object) -> None:
    """A second producer run writes exactly the first run's bytes."""
    from livespec_dev_tooling import ci_priority_record

    value = '{"default":"low","generated_at":"2026-11-22T00:00:00Z","items":{},"radar_commit":"sha","schema":1}'
    monkeypatch.setattr(ci_priority_record, "_run", lambda *_args: value)  # type: ignore[attr-defined]

    assert (
        _matching_generated_at(
            repositories=("livespec-ai/livespec",),
            record={
                "schema": 1,
                "radar_commit": "sha",
                "items": {},
                "default": "low",
                "generated_at": "",
            },
        )
        == "2026-11-22T00:00:00Z"
    )


def test_dry_run_prints_each_fleet_value_without_writing(
    monkeypatch: object, tmp_path: Path, capsys: object
) -> None:
    """Dry-run reports the complete fleet plan but never calls variable set."""
    from livespec_dev_tooling import ci_priority_record

    projection = tmp_path / "projection.json"
    projection.write_text(json.dumps([]), encoding="utf-8")
    config = tmp_path / "config.jsonc"
    config.write_text('{"ci":{"priority_bands":{"high":1,"medium":2}}}', encoding="utf-8")
    manifest = tmp_path / "fleet.jsonc"
    manifest.write_text(
        '{"owner":"acme","fleet":[{"repo":"one"},{"repo":"two"}]}', encoding="utf-8"
    )
    calls: list[tuple[str, ...]] = []

    def fake_run(*args: str) -> str:
        calls.append(args)
        return ""

    monkeypatch.setattr(ci_priority_record, "_run", fake_run)  # type: ignore[attr-defined]

    assert (
        main(
            argv=[
                "--projection",
                str(projection),
                "--config",
                str(config),
                "--fleet-manifest",
                str(manifest),
                "--radar-commit",
                "sha",
                "--generated-at",
                "2026-11-22T00:00:00Z",
                "--dry-run",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "acme/one CI_PRIORITY_RECORD=" in output
    assert "acme/two CI_PRIORITY_RECORD=" in output
    assert not any(command[:3] == ("gh", "variable", "set") for command in calls)


def test_record_ignores_invalid_rows_and_low_bands_and_prefers_the_higher_band() -> None:
    """Only open items owned by the radar's high or medium entries are recorded."""
    radar = (
        RadarEntry(
            kind="item", tenant="tenant", id="shared", words="", said_at=date.today(), blocked_by=()
        ),
        RadarEntry(
            kind="item", tenant="tenant", id="shared", words="", said_at=date.today(), blocked_by=()
        ),
        RadarEntry(
            kind="item", tenant="tenant", id="low", words="", said_at=date.today(), blocked_by=()
        ),
    )

    assert build_record(
        projection=[
            None,
            {},
            {"tenant": "tenant"},
            {"id": "missing-tenant"},
            {"tenant": "tenant", "id": "shared", "status": "ready"},
            {"tenant": "tenant", "id": "low", "status": "ready"},
        ],
        thresholds={"high": 1, "medium": 2},
        radar_commit="sha",
        generated_at="then",
        radar=radar,
    )["items"] == {"shared": "high"}


@pytest.mark.parametrize(
    "thresholds",
    [{}, {"high": "1", "medium": 2}, {"high": 3, "medium": 2}],
)
def test_record_rejects_invalid_band_thresholds(thresholds: dict[str, object]) -> None:
    with pytest.raises(PriorityRecordError, match="priority_bands"):
        build_record(projection=[], thresholds=thresholds, radar_commit="sha", generated_at="then")


def test_jsonc_helpers_and_repository_validation(tmp_path: Path, monkeypatch: object) -> None:
    from livespec_dev_tooling import ci_priority_record

    with pytest.raises(PriorityRecordError, match="JSON object"):
        _jsonc_text(text="[]")
    with pytest.raises(PriorityRecordError, match="owner and fleet"):
        _repositories(manifest={})
    with pytest.raises(PriorityRecordError, match="no repositories"):
        _repositories(manifest={"owner": "acme", "fleet": [None, {"repo": 1}]})
    assert _repositories(
        manifest={"owner": "acme", "fleet": [None, {"repo": 1}, {"repo": "one"}]}
    ) == ("acme/one",)

    manifest = tmp_path / "fleet.jsonc"
    manifest.write_text('{"owner":"acme","fleet":[{"repo":"one"}]}', encoding="utf-8")
    assert _manifest(path=manifest)["owner"] == "acme"
    monkeypatch.setattr(ci_priority_record, "_run", lambda *_args: manifest.read_text())  # type: ignore[attr-defined]
    assert _manifest(path=None)["fleet"] == [{"repo": "one"}]


def test_run_and_matching_timestamp_handle_errors_and_nonmatching_values(
    monkeypatch: object,
) -> None:
    from livespec_dev_tooling import ci_priority_record

    monkeypatch.setattr(  # type: ignore[attr-defined]
        ci_priority_record,
        "subprocess",
        type(
            "Subprocess",
            (),
            {
                "run": staticmethod(
                    lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "ok", "")
                )
            },
        ),
    )
    assert _run("command") == "ok"
    monkeypatch.setattr(  # type: ignore[attr-defined]
        ci_priority_record,
        "subprocess",
        type(
            "Subprocess",
            (),
            {
                "run": staticmethod(
                    lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, "", "bad")
                )
            },
        ),
    )
    with pytest.raises(PriorityRecordError, match="bad"):
        _run("command")

    responses = iter(
        ["not json", "[]", '{"generated_at": 1}', '{"generated_at":"then","schema":2}']
    )
    monkeypatch.setattr(ci_priority_record, "_run", lambda *_args: next(responses))  # type: ignore[attr-defined]
    assert (
        _matching_generated_at(
            repositories=("one", "two", "three", "four"), record={"schema": 1, "generated_at": ""}
        )
        is None
    )


def test_main_writes_timestamped_record_and_rejects_bad_inputs(
    monkeypatch: object, tmp_path: Path, capsys: object
) -> None:
    from livespec_dev_tooling import ci_priority_record

    projection = tmp_path / "projection.json"
    projection.write_text("[]", encoding="utf-8")
    manifest = tmp_path / "fleet.jsonc"
    manifest.write_text('{"owner":"acme","fleet":[{"repo":"one"}]}', encoding="utf-8")
    config = tmp_path / "config.jsonc"
    config.write_text('{"ci":{"priority_bands":{"high":1,"medium":2}}}', encoding="utf-8")
    writes: list[tuple[str, ...]] = []

    def fake_run(*args: str) -> str:
        writes.append(args)
        return ""

    monkeypatch.setattr(ci_priority_record, "_run", fake_run)  # type: ignore[attr-defined]
    monkeypatch.setattr(ci_priority_record, "_MAX_VARIABLE_BYTES", 10000)  # type: ignore[attr-defined]
    assert (
        main(
            argv=[
                "--projection",
                str(projection),
                "--config",
                str(config),
                "--fleet-manifest",
                str(manifest),
            ]
        )
        == 0
    )
    assert any(command[:3] == ("gh", "variable", "set") for command in writes)
    assert "acme/one CI_PRIORITY_RECORD=" in capsys.readouterr().out  # type: ignore[attr-defined]

    for text, message in [
        ("{}", "priority_bands"),
        ('{"ci":{}}', "priority_bands"),
        ("[]", "JSON object"),
    ]:
        config.write_text(text, encoding="utf-8")
        with pytest.raises(PriorityRecordError, match=message):
            main(
                argv=[
                    "--projection",
                    str(projection),
                    "--config",
                    str(config),
                    "--fleet-manifest",
                    str(manifest),
                ]
            )
    config.write_text('{"ci":{"priority_bands":{"high":1,"medium":2}}}', encoding="utf-8")
    projection.write_text("{}", encoding="utf-8")
    with pytest.raises(PriorityRecordError, match="JSON array"):
        main(
            argv=[
                "--projection",
                str(projection),
                "--config",
                str(config),
                "--fleet-manifest",
                str(manifest),
            ]
        )


def test_main_refuses_oversized_variable(monkeypatch: object, tmp_path: Path) -> None:
    from livespec_dev_tooling import ci_priority_record

    projection = tmp_path / "projection.json"
    projection.write_text("[]", encoding="utf-8")
    config = tmp_path / "config.jsonc"
    config.write_text('{"ci":{"priority_bands":{"high":1,"medium":2}}}', encoding="utf-8")
    manifest = tmp_path / "fleet.jsonc"
    manifest.write_text('{"owner":"acme","fleet":[{"repo":"one"}]}', encoding="utf-8")
    monkeypatch.setattr(ci_priority_record, "_MAX_VARIABLE_BYTES", 1)  # type: ignore[attr-defined]
    with pytest.raises(PriorityRecordError, match="limit is 1"):
        main(
            argv=[
                "--projection",
                str(projection),
                "--config",
                str(config),
                "--fleet-manifest",
                str(manifest),
                "--radar-commit",
                "sha",
                "--generated-at",
                "then",
            ]
        )
