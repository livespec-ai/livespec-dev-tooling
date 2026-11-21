"""Refuse unmeasured changes to CI capacity, quotas, and lanes."""

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_VENDOR_DIR = Path(__file__).resolve().parent.parent / "_vendor"
if str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

import structlog  # noqa: E402  — vendor-path-aware import after sys.path insert.

__all__: list[str] = []

CHECK_PURITY = "world-reading"

_DERIVATION = Path("ci-runner/k3s/phase2/kueue/DERIVATION.md")
_RATIFICATION_DATE = date(2026, 11, 17)
_DATED_HEADING = re.compile(r"^##\s+(?P<heading>.+?\s+\((?P<date>\d{4}-\d{2}-\d{2})\))\s*$")
_CHANGE_WORDS = ("capacity", "quota", "lane", "churn-slot")
_WINDOW = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:minutes?|mins?|hours?|hrs?|days?|[mhd])\b", re.IGNORECASE
)
_REVERT_VALUE = re.compile(r"(?:->|\bto\s+)\s*\d+(?:\.\d+)?", re.IGNORECASE)


@dataclass(frozen=True, kw_only=True)
class _Section:
    heading: str
    recorded_on: date
    start: int
    end: int
    body: str


def _configure_logger() -> structlog.stdlib.BoundLogger:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )
    return structlog.get_logger("capacity_change_derivation")


def _git_diff(*, cwd: Path, selector: str) -> str | None:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    paths = (
        str(_DERIVATION),
        "ci-runner/k3s/phase2/kueue",
        "ci-runner/k3s/phase2/node-cpu-budget.yaml",
        "ci-runner/k3s/phase0-bare-metal/profiles",
    )
    completed = subprocess.run(
        ["git", "diff", "--unified=0", "--no-ext-diff", selector, "--", *paths],
        capture_output=True,
        check=False,
        cwd=cwd,
        env=env,
        text=True,
    )
    return completed.stdout if completed.returncode == 0 else None


def _available_diffs(*, cwd: Path) -> tuple[str, ...] | None:
    head = _git_diff(cwd=cwd, selector="HEAD")
    if head is None:
        return None
    branch = _git_diff(cwd=cwd, selector="origin/master...HEAD")
    return (head,) if branch is None else (head, branch)


def _changed_lines(*, diff: str) -> dict[str, set[int]]:
    changed: dict[str, set[int]] = {}
    path = ""
    line = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            path = raw.removeprefix("+++ b/")
            continue
        if raw.startswith("@@ "):
            match = re.search(r"\+(\d+)", raw)
            line = int(match.group(1)) if match is not None else 0
            continue
        if not path or line == 0 or raw.startswith("---"):
            continue
        if raw.startswith("+"):
            changed.setdefault(path, set()).add(line)
            line += 1
        elif not raw.startswith("-"):
            line += 1
    return changed


def _changed_values(*, diff: str) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    path = ""
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            path = raw.removeprefix("+++ b/")
            continue
        if not path or not raw.startswith(("+", "-")) or raw.startswith(("+++", "---")):
            continue
        value = raw[1:].strip()
        if path.startswith("ci-runner/k3s/phase0-bare-metal/profiles/"):
            relevant = value.startswith("ADMISSION_CAPACITY_C=")
        elif path == "ci-runner/k3s/phase2/node-cpu-budget.yaml":
            relevant = bool(re.match(r"(?:gate_cpu|repro_cpu):\s*\d", value))
        else:
            relevant = path.startswith("ci-runner/k3s/phase2/kueue/cluster-queue-") and bool(
                re.search(
                    r"(?:nominalQuota|lendingLimit|maxCount|gate-unit|cpu|memory):\s*[\"']?\d",
                    value,
                )
            )
        if relevant:
            values.append((path, value))
    return tuple(values)


def _sections(*, path: Path) -> tuple[_Section, ...]:
    lines = path.read_text(encoding="utf-8").splitlines()
    found: list[_Section] = []
    for index, line in enumerate(lines):
        match = _DATED_HEADING.match(line)
        if match is None:
            continue
        end = next(
            (
                candidate
                for candidate in range(index + 1, len(lines))
                if lines[candidate].startswith("## ")
            ),
            len(lines),
        )
        found.append(
            _Section(
                heading=match.group("heading"),
                recorded_on=date.fromisoformat(match.group("date")),
                start=index + 1,
                end=end,
                body="\n".join(lines[index:end]),
            )
        )
    return tuple(found)


def _is_capacity_change(*, section: _Section) -> bool:
    text = section.body.lower()
    return any(word in text for word in _CHANGE_WORDS)


def _missing_evidence(*, section: _Section) -> tuple[str, ...]:
    text = section.body.lower()
    missing: list[str] = []
    for required, marker in (
        ("+2 h CI-side read", "+2 h ci-side read"),
        ("CI queue-wait p95", "ci queue-wait p95"),
        ("CI job duration p50", "ci job duration p50"),
        ("duration_ms under one day", "duration_ms under one day"),
        ("node CI-slice cpu.pressure", "node ci-slice cpu.pressure"),
    ):
        if marker not in text:
            missing.append(required)
    metrics = ("queue-wait", "duration", "cpu.pressure", "cpu psi", "diskpressure", "memory")
    if "revert" not in text or not any(word in text for word in metrics):
        missing.append("measured revert trigger named metric")
    if "revert" not in text or _WINDOW.search(text) is None:
        missing.append("measured revert trigger window")
    if "revert" not in text or _REVERT_VALUE.search(text) is None:
        missing.append("measured revert trigger value the change reverts to")
    return tuple(missing)


def _changed_context(
    *, diffs: tuple[str, ...]
) -> tuple[dict[str, set[int]], tuple[tuple[str, str], ...]]:
    changed: dict[str, set[int]] = {}
    values: list[tuple[str, str]] = []
    for diff in diffs:
        for path, lines in _changed_lines(diff=diff).items():
            changed.setdefault(path, set()).update(lines)
        values.extend(_changed_values(diff=diff))
    return changed, tuple(values)


def main() -> int:
    """Report every post-ratification capacity derivation lacking its evidence."""
    log = _configure_logger()
    cwd = Path.cwd()
    derivation = cwd / _DERIVATION
    if not derivation.is_file():
        return 0
    sections = _sections(path=derivation)
    diffs = _available_diffs(cwd=cwd)
    changed, values = _changed_context(diffs=diffs) if diffs is not None else ({}, ())
    candidates = tuple(
        section
        for section in sections
        if section.recorded_on >= _RATIFICATION_DATE
        and _is_capacity_change(section=section)
        and (
            diffs is None
            or any(
                section.start <= line < section.end for line in changed.get(str(_DERIVATION), set())
            )
        )
    )
    failures = 0
    if values and not candidates:
        for path, value in values:
            log.error(
                "capacity, quota, or lane value lacks a changed dated DERIVATION.md section",
                check_id="capacity_change_derivation",
                path=path,
                value=value,
                missing="new or changed dated DERIVATION.md section",
            )
            failures += 1
    for section in candidates:
        missing = _missing_evidence(section=section)
        if missing:
            log.error(
                "capacity derivation evidence is incomplete",
                check_id="capacity_change_derivation",
                heading=section.heading,
                missing=missing,
            )
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
