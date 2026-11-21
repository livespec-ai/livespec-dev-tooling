"""Green-leg coverage for the capacity-change derivation guard."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from livespec_dev_tooling.checks import capacity_change_derivation as subject

__all__: list[str] = []


def _write_derivation(*, root: Path, body: str) -> None:
    path = root / "ci-runner/k3s/phase2/kueue/DERIVATION.md"
    path.parent.mkdir(parents=True)
    _ = path.write_text(body, encoding="utf-8")


def _complete_section() -> str:
    return (
        "## Gate lane adjustment (2026-11-21)\n\n"
        "The +2 h CI-side read records CI queue-wait p95, CI job duration p50, "
        "duration_ms under one day, and node CI-slice cpu.pressure.\n\n"
        "Revert trigger: cpu.pressure over a 5 minute window reverts to 2.\n"
    )


def test_main_accepts_complete_post_ratification_derivation(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_derivation(root=tmp_path, body=_complete_section())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(subject, "_available_diffs", lambda **_kwargs: None)
    assert subject.main() == 0


def test_main_names_changed_value_when_no_changed_derivation_exists(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_derivation(root=tmp_path, body="## Historical capacity (2026-11-16)\n")
    diff = (
        "+++ b/ci-runner/k3s/phase0-bare-metal/profiles/test.env\n"
        "-ADMISSION_CAPACITY_C=2\n"
        "+ADMISSION_CAPACITY_C=3\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(subject, "_available_diffs", lambda **_kwargs: (diff,))
    assert subject.main() == 1
    captured = capsys.readouterr().err
    assert "profiles/test.env" in captured
    assert "ADMISSION_CAPACITY_C=3" in captured


def test_changed_value_reader_covers_each_protected_surface() -> None:
    diff = "\n".join(
        (
            "+++ b/ci-runner/k3s/phase0-bare-metal/profiles/test.env",
            "+ADMISSION_CAPACITY_C=3",
            "+++ b/ci-runner/k3s/phase2/node-cpu-budget.yaml",
            "+    gate_cpu: 10",
            "+++ b/ci-runner/k3s/phase2/kueue/cluster-queue-test.yaml",
            "+        nominalQuota: 3",
            "+++ b/ignored.yaml",
            "+        nominalQuota: 99",
            "+this is not a protected value",
        )
    )
    assert subject._changed_values(diff=diff) == (  # noqa: SLF001 — private parser under test.
        ("ci-runner/k3s/phase0-bare-metal/profiles/test.env", "ADMISSION_CAPACITY_C=3"),
        ("ci-runner/k3s/phase2/node-cpu-budget.yaml", "gate_cpu: 10"),
        ("ci-runner/k3s/phase2/kueue/cluster-queue-test.yaml", "nominalQuota: 3"),
    )


def test_changed_context_merges_each_diff_and_missing_derivation_passes(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    diff_one = "+++ b/ci-runner/k3s/phase2/kueue/DERIVATION.md\n@@ -0 +1 @@\n+line\n"
    diff_two = "+++ b/ci-runner/k3s/phase2/kueue/DERIVATION.md\n@@ -0 +2 @@\n+line\n"
    changed, values = subject._changed_context(diffs=(diff_one, diff_two))  # noqa: SLF001
    assert changed == {"ci-runner/k3s/phase2/kueue/DERIVATION.md": {1, 2}}
    assert values == ()
    monkeypatch.chdir(tmp_path)
    assert subject.main() == 0


def test_changed_line_reader_tracks_added_lines_only() -> None:
    diff = "\n".join(
        (
            "+++ b/ci-runner/k3s/phase2/kueue/DERIVATION.md",
            "@@ -1 +3,2 @@",
            "-old",
            "+new",
            " context",
            "+last",
        )
    )
    assert subject._changed_lines(diff=diff) == {  # noqa: SLF001 — private parser under test.
        "ci-runner/k3s/phase2/kueue/DERIVATION.md": {3, 5}
    }


def test_git_diff_success_and_available_diff_fallbacks(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="diff", stderr="")
    monkeypatch.setattr(subject.subprocess, "run", lambda *_args, **_kwargs: completed)
    assert subject._git_diff(cwd=tmp_path, selector="HEAD") == "diff"  # noqa: SLF001
    calls: list[str] = []

    def fake_diff(**kwargs: Path | str) -> str | None:
        selector = kwargs["selector"]
        assert isinstance(selector, str)
        calls.append(selector)
        return "head" if selector == "HEAD" else None

    monkeypatch.setattr(subject, "_git_diff", fake_diff)
    assert subject._available_diffs(cwd=tmp_path) == ("head",)  # noqa: SLF001
    assert calls == ["HEAD", "origin/master...HEAD"]


def test_evidence_reader_requires_every_required_element(tmp_path: Path) -> None:
    _write_derivation(root=tmp_path, body=_complete_section())
    section = subject._sections(  # noqa: SLF001 — private parser under test.
        path=tmp_path / "ci-runner/k3s/phase2/kueue/DERIVATION.md"
    )[0]
    assert subject._is_capacity_change(section=section)  # noqa: SLF001
    assert subject._missing_evidence(section=section) == ()  # noqa: SLF001
