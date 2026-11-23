"""The duration-table generator lists every test file its pytest timings name."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

__all__: list[str] = []

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GENERATOR = _REPO_ROOT / "scripts" / "just" / "coverage-shard-durations.sh"

_CANNED_LOG = """\
============================= slowest durations =============================
2.50s call     tests/pkg/test_alpha.py::test_one
0.25s setup    tests/pkg/test_alpha.py::test_one
1.00s call     tests/pkg/test_alpha.py::test_two
4.00s call     tests/other/test_beta.py::test_only
0.00s teardown tests/other/test_beta.py::test_only
0.10s call     tests/test_gamma.py::test_param[a-b]
====================== 4 passed in 8.00s ======================
"""


def test_the_generator_lists_every_test_file_in_the_timings_it_reads(*, tmp_path: Path) -> None:
    log = tmp_path / "pytest.log"
    log.write_text(_CANNED_LOG, encoding="utf-8")
    table = tmp_path / "durations.tsv"

    subprocess.run(
        [str(_GENERATOR)],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "LIVESPEC_COVERAGE_SHARD_PYTEST_LOG": str(log),
            "LIVESPEC_COVERAGE_SHARD_DURATIONS_OUT": str(table),
        },
    )

    rows = [line.split("\t") for line in table.read_text(encoding="utf-8").splitlines()]
    assert rows == [
        ["tests/other/test_beta.py", "4.000"],
        ["tests/pkg/test_alpha.py", "3.750"],
        ["tests/test_gamma.py", "0.100"],
    ]
