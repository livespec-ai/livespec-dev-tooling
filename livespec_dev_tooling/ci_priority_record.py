"""Produce the fleet's ``CI_PRIORITY_RECORD`` repository variable.

The coordinator supplies the current per-tenant ``list-work-items --json``
projection as one JSON array.  Every row needs ``tenant``, ``id``, ``status``
and (when it has one) ``parent``.  Keeping the projection as input makes this
writer independent of ledger credentials while preserving the radar as the
only ordering source.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from livespec_dev_tooling.radar.radar import RADAR, RadarEntry

__all__: list[str] = ["build_record", "main"]

_MAX_VARIABLE_BYTES = 48 * 1024
_BAND_SCORE = {"low": 0, "medium": 1, "high": 2}
_MANIFEST_ENDPOINT = "repos/livespec-ai/livespec/contents/.livespec-fleet-manifest.jsonc?ref=master"


class PriorityRecordError(Exception):
    """The producer cannot derive or write a conforming record."""


def _records(*, rows: Iterable[object]) -> dict[tuple[str, str], Mapping[str, object]]:
    records: dict[tuple[str, str], Mapping[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        record = cast("Mapping[str, object]", row)
        tenant, identifier = record.get("tenant"), record.get("id")
        if isinstance(tenant, str) and isinstance(identifier, str):
            records[(tenant, identifier)] = record
    return records


def _open_children(
    *, entry: RadarEntry, records: Mapping[tuple[str, str], Mapping[str, object]]
) -> set[str]:
    prefix = f"{entry.id}."
    return {
        identifier
        for (tenant, identifier), record in records.items()
        if tenant == entry.tenant
        and record.get("status") not in {"closed", "done"}
        and (identifier.startswith(prefix) or record.get("parent") == entry.id)
    }


def _band(*, index: int, thresholds: Mapping[str, object]) -> str:
    high, medium = thresholds.get("high"), thresholds.get("medium")
    if not isinstance(high, int) or not isinstance(medium, int) or high > medium:
        raise PriorityRecordError(  # noqa: TRY003
            "ci.priority_bands must map high and medium to ascending integers"
        )
    if index <= high:
        return "high"
    return "medium" if index <= medium else "low"


def build_record(
    *,
    projection: Iterable[object],
    thresholds: Mapping[str, object],
    radar_commit: str,
    generated_at: str,
    radar: Sequence[RadarEntry] = RADAR,
) -> dict[str, object]:
    """Build the stable record from the radar and a list-work-items projection."""
    records = _records(rows=projection)
    items: dict[str, str] = {}
    for index, entry in enumerate(radar, start=1):
        band = _band(index=index, thresholds=thresholds)
        if band == "low":
            continue
        identifiers = (
            _open_children(entry=entry, records=records) if entry.kind == "plan" else {entry.id}
        )
        for identifier in identifiers:
            prior = items.get(identifier, "low")
            if _BAND_SCORE[band] > _BAND_SCORE[prior]:
                items[identifier] = band
    return {
        "schema": 1,
        "generated_at": generated_at,
        "radar_commit": radar_commit,
        "items": dict(sorted(items.items())),
        "default": "low",
    }


def _jsonc_text(*, text: str) -> Mapping[str, object]:
    vendor = Path(__file__).resolve().parent / "_vendor"
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    import jsoncomment

    parsed = jsoncomment.loads(text)
    if not isinstance(parsed, dict):
        raise PriorityRecordError("JSONC must be a JSON object")  # noqa: TRY003
    return cast("Mapping[str, object]", parsed)


def _jsonc(*, path: Path) -> Mapping[str, object]:
    return _jsonc_text(text=path.read_text(encoding="utf-8"))


def _run(*args: str) -> str:
    result = subprocess.run(args, check=False, capture_output=True, text=True)  # noqa: S603
    if result.returncode:
        raise PriorityRecordError(result.stderr.strip() or f"{' '.join(args)} failed")
    return result.stdout


def _manifest(*, path: Path | None) -> Mapping[str, object]:
    text = (
        path.read_text(encoding="utf-8")
        if path is not None
        else _run("gh", "api", _MANIFEST_ENDPOINT, "-H", "Accept: application/vnd.github.raw")
    )
    return _jsonc_text(text=text)


def _repositories(*, manifest: Mapping[str, object]) -> tuple[str, ...]:
    owner, fleet = manifest.get("owner"), manifest.get("fleet")
    if not isinstance(owner, str) or not isinstance(fleet, list):
        raise PriorityRecordError("fleet manifest must carry owner and fleet")  # noqa: TRY003
    fleet_records = cast("list[object]", fleet)
    repositories: list[str] = []
    for entry in fleet_records:
        if not isinstance(entry, dict):
            continue
        repository = cast("Mapping[str, object]", entry).get("repo")
        if isinstance(repository, str):
            repositories.append(f"{owner}/{repository}")
    if not repositories:
        raise PriorityRecordError("fleet manifest has no repositories")  # noqa: TRY003
    return tuple(repositories)


def _matching_generated_at(
    *, repositories: Sequence[str], record: Mapping[str, object]
) -> str | None:
    """Reuse a matching record's timestamp so unchanged runs are byte-identical."""
    comparable = dict(record)
    _ = comparable.pop("generated_at", None)
    for repository in repositories:
        try:
            existing = json.loads(
                _run("gh", "variable", "get", "CI_PRIORITY_RECORD", "--repo", repository)
            )
        except (PriorityRecordError, json.JSONDecodeError):
            continue
        if not isinstance(existing, dict):
            continue
        existing_record = cast("Mapping[str, object]", existing)
        generated_at = existing_record.get("generated_at")
        if not isinstance(generated_at, str):
            continue
        candidate = dict(existing_record)
        _ = candidate.pop("generated_at", None)
        if candidate == comparable:
            return generated_at
    return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--projection", type=Path, required=True)
    _ = parser.add_argument("--fleet-manifest", type=Path)
    _ = parser.add_argument("--config", type=Path, default=Path(".livespec.jsonc"))
    _ = parser.add_argument("--radar-commit", default=None)
    _ = parser.add_argument("--generated-at", default=None)
    _ = parser.add_argument("--dry-run", action="store_true")
    return parser


def main(*, argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = _jsonc(path=args.config)
    ci = config.get("ci")
    if not isinstance(ci, dict):
        raise PriorityRecordError(".livespec.jsonc must declare ci.priority_bands")  # noqa: TRY003
    priority_bands = cast("Mapping[str, object]", ci).get("priority_bands")
    if not isinstance(priority_bands, dict):
        raise PriorityRecordError(".livespec.jsonc must declare ci.priority_bands")  # noqa: TRY003
    projection_payload = json.loads(args.projection.read_text(encoding="utf-8"))
    if not isinstance(projection_payload, list):
        raise PriorityRecordError(  # noqa: TRY003
            "--projection must contain a list-work-items JSON array"
        )
    projection = cast("list[object]", projection_payload)
    radar_commit = (
        args.radar_commit
        or _run("git", "rev-parse", "HEAD:livespec_dev_tooling/radar/radar.py").strip()
    )
    provisional = build_record(
        projection=projection,
        thresholds=cast("Mapping[str, object]", priority_bands),
        radar_commit=radar_commit,
        generated_at="",
    )
    repositories = _repositories(manifest=_manifest(path=args.fleet_manifest))
    generated_at = args.generated_at or _matching_generated_at(
        repositories=repositories, record=provisional
    )
    if generated_at is None:
        generated_at = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
    record = {**provisional, "generated_at": generated_at}
    value = json.dumps(record, separators=(",", ":"), sort_keys=True)
    size = len(value.encode("utf-8"))
    if size > _MAX_VARIABLE_BYTES:
        raise PriorityRecordError(  # noqa: TRY003
            f"CI_PRIORITY_RECORD is {size} bytes; limit is {_MAX_VARIABLE_BYTES}"
        )
    for repository in repositories:
        print(f"{repository} CI_PRIORITY_RECORD={value}")  # noqa: T201
        if not args.dry_run:
            _ = _run(
                "gh", "variable", "set", "CI_PRIORITY_RECORD", "--repo", repository, "--body", value
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
