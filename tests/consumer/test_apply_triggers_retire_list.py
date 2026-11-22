"""Consumer-tier: apply-triggers.sh retires a listed trigger by exact name once its replacement is live.

`livespec-dev-tooling-wgmoem`. The script runs unmodified against a stateful
loopback stub of the Honeycomb trigger API that records every request, so "sent
no DELETE" is measured off the wire.
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
_DATASET = "metrics"
_OLD = "host NVMe media errors — old one"
_NEW = "host NVMe — merged one"
_BYSTANDER = "host unrelated trigger"


def _trigger(trigger_id: str, name: str, *, disabled: bool = False) -> dict[str, object]:
    return {"id": trigger_id, "name": name, "disabled": disabled}


class _State:
    def __init__(self, live: list[dict[str, object]]) -> None:
        self.live = live
        self.requests: list[tuple[str, str]] = []


def _serve(state: _State) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _route(self) -> None:
            state.requests.append((self.command, self.path))
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                _ = self.rfile.read(length)
            parts = self.path.strip("/").split("/")
            status, payload = 200, {"id": "written"}
            if self.command == "GET" and len(parts) == 3:
                payload = state.live  # type: ignore[assignment]
            elif self.command == "GET" and len(parts) == 4:
                found = [t for t in state.live if t["id"] == parts[3]]
                status, payload = (200, found[0]) if found else (404, {"error": "none"})
            elif self.command == "DELETE":
                state.live[:] = [t for t in state.live if t["id"] != parts[3]]
                status, payload = 200, {}
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            _ = self.wfile.write(raw)

        do_GET = _route  # noqa: N815
        do_POST = _route  # noqa: N815
        do_PUT = _route  # noqa: N815
        do_DELETE = _route  # noqa: N815

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


@pytest.fixture
def stub(request: pytest.FixtureRequest) -> Iterator[tuple[_State, str]]:
    live: list[dict[str, object]] = getattr(request, "param", [])
    state = _State([dict(t) for t in live])
    server = _serve(state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _stage(tmp_path: Path, retire_lines: list[str]) -> Path:
    directory = tmp_path / "triggers"
    directory.mkdir()
    staged = directory / _SCRIPT.name
    _ = shutil.copy2(_SCRIPT, staged)
    definition = {"name": _NEW, "description": "d", "query": {"time_range": 600}}
    _ = (directory / "merged.json").write_text(json.dumps(definition), encoding="utf-8")
    _ = (directory / "retired-triggers.txt").write_text(
        "\n".join(["# comment", "", *retire_lines]) + "\n", encoding="utf-8"
    )
    return staged


def _run(script: Path, api: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/"),
        "HONEYCOMB_API": api,
        "HONEYCOMB_CONFIG_KEY_LIVESPEC": "stub-key",
    }
    return subprocess.run(
        ["bash", str(script), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _line(old: str = _OLD, new: str = _NEW) -> str:
    return f"{_DATASET}\t{old}\t{new}"


_BOTH = [_trigger("t-old", _OLD), _trigger("t-new", _NEW), _trigger("t-by", _BYSTANDER)]


@pytest.mark.parametrize("stub", [_BOTH], indirect=True)
def test_apply_deletes_only_the_listed_name_when_the_replacement_is_live(
    tmp_path: Path, stub: tuple[_State, str]
) -> None:
    state, api = stub
    result = _run(_stage(tmp_path, [_line()]), api)
    assert result.returncode == 0, result.stderr
    assert f"retired t-old [{_DATASET}] {_OLD}" in result.stdout
    assert [t["id"] for t in state.live] == ["t-new", "t-by"]
    assert [p for m, p in state.requests if m == "DELETE"] == [f"/1/triggers/{_DATASET}/t-old"]


@pytest.mark.parametrize("stub", [[_trigger("t-new", _NEW)]], indirect=True)
def test_an_absent_name_is_reported_already_retired(
    tmp_path: Path, stub: tuple[_State, str]
) -> None:
    state, api = stub
    result = _run(_stage(tmp_path, [_line()]), api)
    assert result.returncode == 0
    assert f"already-retired {_OLD}" in result.stdout
    assert not any(m == "DELETE" for m, _ in state.requests)


@pytest.mark.parametrize(
    "stub",
    [
        [_trigger("t-old", _OLD)],
        [_trigger("t-old", _OLD), _trigger("t-new", _NEW, disabled=True)],
    ],
    indirect=True,
)
def test_a_missing_or_disabled_replacement_keeps_the_old_trigger(
    tmp_path: Path, stub: tuple[_State, str]
) -> None:
    state, api = stub
    result = _run(_stage(tmp_path, [_line()]), api)
    assert result.returncode != 0
    assert "FAILED retire" in result.stderr
    assert any(t["id"] == "t-old" for t in state.live)
    assert not any(m == "DELETE" for m, _ in state.requests)


@pytest.mark.parametrize("stub", [_BOTH], indirect=True)
def test_a_name_not_in_the_list_is_never_deleted(tmp_path: Path, stub: tuple[_State, str]) -> None:
    state, api = stub
    result = _run(_stage(tmp_path, [_line(old="host something else entirely")]), api)
    assert result.returncode == 0
    assert {t["id"] for t in state.live} == {"t-old", "t-new", "t-by"}
    assert not any(m == "DELETE" for m, _ in state.requests)


@pytest.mark.parametrize("stub", [_BOTH], indirect=True)
def test_drift_mode_reports_retire_pending_and_sends_no_write(
    tmp_path: Path, stub: tuple[_State, str]
) -> None:
    state, api = stub
    result = _run(_stage(tmp_path, [_line()]), api, "--drift")
    assert result.returncode != 0
    assert f"retire-pending {_OLD}" in result.stdout
    assert all(m == "GET" for m, _ in state.requests)
