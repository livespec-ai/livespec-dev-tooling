"""Consumer-tier: apply-triggers.sh refuses xtrace, keeps its key out of argv, skips a missing dataset.

`livespec-dev-tooling-a7rwrn`. The script is run unmodified against a loopback
stub of the Honeycomb API. A recording `curl` stand-in on PATH logs every
argument vector and then runs the real curl, so "the key is in no argv" is
measured off the process arguments, not read from the source.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

__all__: list[str] = []

pytestmark = pytest.mark.consumer

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "ci-runner"
    / "observability"
    / "triggers"
    / "apply-triggers.sh"
)
_KEY = "SENTINEL-honeycomb-config-key-0123"
_TIMEOUT_S = 60
_MISSING = "no-such-dataset"


def _definition(name: str, dataset: str) -> dict[str, object]:
    return {
        "name": name,
        "dataset": dataset,
        "description": "d",
        "query": {"calculations": [{"op": "COUNT"}], "time_range": 600},
        "threshold": {"op": ">", "value": 1},
        "frequency": 600,
        "recipients": [],
    }


class _State:
    def __init__(self, answers: dict[str, tuple[int, object]]) -> None:
        self.answers = answers
        self.requests: list[tuple[str, str, str]] = []


def _serve(state: _State) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _route(self) -> None:
            state.requests.append(
                (self.command, self.path, self.headers.get("X-Honeycomb-Team") or "")
            )
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                _ = self.rfile.read(length)
            dataset = self.path.rstrip("/").split("/")[-1]
            if self.command == "GET":
                status, payload = state.answers.get(dataset, (200, []))
            else:
                status, payload = 200, {"id": "written"}
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            _ = self.wfile.write(raw)

        do_GET = _route  # noqa: N815
        do_POST = _route  # noqa: N815
        do_PUT = _route  # noqa: N815

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


@pytest.fixture
def stub(request: pytest.FixtureRequest) -> Iterator[tuple[_State, str]]:
    answers: dict[str, tuple[int, object]] = getattr(request, "param", {})
    state = _State(answers)
    server = _serve(state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _stage(tmp_path: Path, names_datasets: list[tuple[str, str]]) -> tuple[Path, Path, Path]:
    directory = tmp_path / "triggers"
    directory.mkdir()
    staged = directory / _SCRIPT.name
    _ = shutil.copy2(_SCRIPT, staged)
    for index, (name, dataset) in enumerate(names_datasets):
        _ = (directory / f"{index}.json").write_text(
            json.dumps(_definition(name, dataset)), encoding="utf-8"
        )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_log = tmp_path / "argv.log"
    real = shutil.which("curl")
    assert real is not None
    shim = bin_dir / "curl"
    _ = shim.write_text(
        f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "{argv_log}"\nexec "{real}" "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return staged, bin_dir, argv_log


def _run(
    script: Path,
    bin_dir: Path,
    api: str,
    *args: str,
    shell_args: tuple[str, ...] = (),
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", "/"),
        "HONEYCOMB_API": api,
        "HONEYCOMB_CONFIG_KEY_LIVESPEC": _KEY,
        **(extra_env or {}),
    }
    return subprocess.run(
        ["bash", *shell_args, str(script), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
        check=False,
    )


def test_bash_x_is_refused_and_prints_no_key(tmp_path: Path) -> None:
    script, bin_dir, _ = _stage(tmp_path, [("a", "metrics")])
    result = _run(script, bin_dir, "http://127.0.0.1:9", shell_args=("-x",))
    assert result.returncode == 2
    assert _KEY not in result.stdout + result.stderr
    assert "xtrace" in result.stderr


def test_shellopts_xtrace_is_refused_and_prints_no_key(tmp_path: Path) -> None:
    script, bin_dir, _ = _stage(tmp_path, [("a", "metrics")])
    result = _run(script, bin_dir, "http://127.0.0.1:9", extra_env={"SHELLOPTS": "xtrace"})
    assert result.returncode == 2
    assert _KEY not in result.stdout + result.stderr


@pytest.mark.parametrize("mode_args", [(), ("--drift",)])
def test_key_is_in_no_argument_vector_and_reaches_the_wire(
    tmp_path: Path, stub: tuple[_State, str], mode_args: tuple[str, ...]
) -> None:
    state, api = stub
    script, bin_dir, argv_log = _stage(tmp_path, [("a", "metrics")])
    _ = _run(script, bin_dir, api, *mode_args)
    assert argv_log.read_text(encoding="utf-8").strip()
    assert _KEY not in argv_log.read_text(encoding="utf-8")
    assert state.requests
    assert all(sent == _KEY for _, _, sent in state.requests)


_MISSING_BODY = {"error": "Dataset not found"}


@pytest.mark.parametrize("stub", [{_MISSING: (404, _MISSING_BODY)}], indirect=True)
@pytest.mark.parametrize(("mode_args", "want_rc"), [((), 0), (("--drift",), 1)])
def test_missing_dataset_is_skipped_reported_and_the_rest_still_run(
    tmp_path: Path, stub: tuple[_State, str], mode_args: tuple[str, ...], want_rc: int
) -> None:
    state, api = stub
    script, bin_dir, _ = _stage(
        tmp_path, [("first missing", _MISSING), ("second present", "metrics")]
    )
    result = _run(script, bin_dir, api, *mode_args)
    assert result.returncode == want_rc
    assert f"dataset-missing first missing {_MISSING}" in result.stdout
    paths = [path for _, path in ((m, p) for m, p, _ in state.requests)]
    assert any(path.endswith("/1/triggers/metrics") for path in paths)
    if not mode_args:
        assert "created" in result.stdout
        assert not any(m == "POST" and _MISSING in p for m, p, _ in state.requests)


@pytest.mark.parametrize(
    "stub",
    [
        {_MISSING: (404, {"error": "not found"})},
        {_MISSING: (401, {"error": "Dataset not found"})},
        {_MISSING: (403, {"error": "forbidden"})},
        {_MISSING: (500, {"error": "boom"})},
    ],
    indirect=True,
)
@pytest.mark.parametrize("mode_args", [(), ("--drift",)])
def test_other_failures_still_fail_the_run(
    tmp_path: Path, stub: tuple[_State, str], mode_args: tuple[str, ...]
) -> None:
    _, api = stub
    script, bin_dir, _ = _stage(tmp_path, [("x", _MISSING)])
    result = _run(script, bin_dir, api, *mode_args)
    assert result.returncode != 0
    assert "FAILED list x" in result.stderr
    assert "dataset-missing" not in result.stdout


def test_transport_error_still_fails_the_run(tmp_path: Path) -> None:
    script, bin_dir, _ = _stage(tmp_path, [("x", "metrics")])
    result = _run(script, bin_dir, "http://127.0.0.1:1")
    assert result.returncode != 0
    assert "FAILED list x" in result.stderr
