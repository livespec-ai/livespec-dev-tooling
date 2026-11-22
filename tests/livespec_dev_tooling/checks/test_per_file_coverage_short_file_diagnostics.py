"""Acceptance test for actionable short-file coverage diagnostics.

The per-file gate must not let a rounded aggregate obscure a short source file.
This fixture has a 99%-covered short file and a fully covered long file, making
the aggregate format as 100.00% while the per-file gate still fails.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from coverage import CoverageData

__all__: list[str] = []


_REPO_ROOT = Path(__file__).resolve().parents[3]
_PER_FILE_COVERAGE = _REPO_ROOT / "livespec_dev_tooling" / "checks" / "per_file_coverage.py"


def _load_per_file_coverage_module() -> object:
    """Load the check freshly so its real main function reads the fixture data."""
    spec = importlib.util.spec_from_file_location(
        "per_file_coverage_short_file_diagnostics", str(_PER_FILE_COVERAGE)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_per_file_coverage_explains_short_file_when_total_rounds_to_100_percent(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A 99% file is named even when the aggregate rounds to 100.00%."""
    short_file = tmp_path / "short.py"
    short_file.write_text(
        "".join(f"line_{line} = {line}\n" for line in range(1, 101)),
        encoding="utf-8",
    )
    long_file = tmp_path / "long.py"
    long_file.write_text(
        "".join(f"line_{line} = {line}\n" for line in range(1, 40_001)),
        encoding="utf-8",
    )

    data = CoverageData(basename=str(tmp_path / ".coverage"), suffix=False)
    data.add_lines(
        {
            str(short_file): list(range(1, 100)),
            str(long_file): list(range(1, 40_001)),
        }
    )
    data.write()

    total_percent = (40_099 / 40_100) * 100
    assert f"{total_percent:.2f}" == "100.00"

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("COVERAGE_FILE", raising=False)
    rc = _load_per_file_coverage_module().main()

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert rc != 0, f"the short file must fail the gate; output={output!r}"
    diagnostic = next(
        json.loads(line)
        for line in output.splitlines()
        if '"event": "file below 100% coverage"' in line
    )
    assert diagnostic["file"].endswith("short.py")
    assert diagnostic["line_percent"] == 99.0
    assert diagnostic["missing_lines"] == [100]
    assert diagnostic.get("missing_branches") == 0
    assert diagnostic.get("partial_branches") == 0
    assert "rounded total coverage is not the pass criterion" in output, output
