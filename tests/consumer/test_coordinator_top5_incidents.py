"""Scenario "top5 prints an INCIDENTS section saying whether each declared incident's record exists".

Rule INCIDENT-IS-A-RECORD (`.ai/coordinator-duties.md` §3): `scripts/coordinator/top5` prints, after
HOLDS, one INCIDENTS line per open `incident:entry` item, read from the incident authority's
`read-current` action and never from labels. These run a copy of the real script against a temporary
HOME, a ledger wrapper stub that answers `bd list` from a fixture and logs every call, and an authority
stub that answers per item id and logs every call. The live ledger, authority and cluster are never read.
"""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

__all__: list[str] = []

pytestmark = pytest.mark.consumer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOP5 = _REPO_ROOT / "scripts" / "coordinator" / "top5"
_REFUSED = 78
_ENTRY_ONLY = "chain state is entry-only with no genesis"
_RECORD = "record exists"
_UNREADABLE = "chain state is unreadable"


def _exe(*, path: Path, body: str) -> None:
    _ = path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _refusal(*, code: str) -> dict[str, object]:
    return {
        "schema": 1,
        "status": "refused",
        "authorizes_current_effects": False,
        "normal_factory_proof": False,
        "result": {"code": code, "detail": "x"},
    }


class _Host:
    """A temporary HOME with a copy of top5, a ledger stub and an authority stub that log their calls."""

    def __init__(self, *, tmp_path: Path) -> None:
        self.home = tmp_path / "home"
        (self.home / "workspace" / "livespec-dev-tooling").mkdir(parents=True)
        coordinator = tmp_path / "coordinator"
        coordinator.mkdir()
        self.script = coordinator / "top5"
        _ = shutil.copy(_TOP5, self.script)
        _exe(path=coordinator / "fleet-utilization.sh", body="#!/bin/sh\nexit 0\n")
        self.ledger_log = tmp_path / "ledger.log"
        self.authority_log = tmp_path / "authority.log"
        self.items = tmp_path / "items.json"
        self.replies = tmp_path / "replies.json"
        self.wrapper = tmp_path / "wrapper.sh"
        self.authority = tmp_path / "authority.py"
        _exe(
            path=self.wrapper,
            body=(
                "#!/bin/sh\n"
                'shift\nprintf "%s\\n" "$*" >> ' + str(self.ledger_log) + "\n"
                'if [ "$2 $3" = "list --label" ]; then cat ' + str(self.items) + "; fi\n"
                "exit 0\n"
            ),
        )
        _exe(
            path=self.authority,
            body=(
                f"#!{sys.executable}\n"
                "import json, sys\n"
                f"open({str(self.authority_log)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
                "argv = sys.argv\n"
                "item = argv[argv.index('--item') + 1]\n"
                f"reply = json.load(open({str(self.replies)!r}))[item]\n"
                "if reply.get('hang'):\n"
                "    import time; time.sleep(600)\n"
                "sys.stdout.write(json.dumps(reply['body']))\n"
                "sys.exit(reply['rc'])\n"
            ),
        )
        self.set_items(items=[])
        self.set_replies(replies={})

    def set_items(self, *, items: list[str]) -> None:
        rows = [{"id": item, "status": "active", "labels": ["incident:entry"]} for item in items]
        _ = self.items.write_text(json.dumps(rows), encoding="utf-8")

    def set_replies(self, *, replies: dict[str, dict[str, object]]) -> None:
        _ = self.replies.write_text(json.dumps(replies), encoding="utf-8")

    def stdout(self, *, timeout_s: str = "60") -> str:
        env = {
            "HOME": str(self.home),
            "PATH": "/usr/bin:/bin",
            "TOP5_LEDGER_WRAPPER": str(self.wrapper),
            "TOP5_INCIDENT_AUTHORITY": str(self.authority),
            "TOP5_INCIDENT_CALL_TIMEOUT_S": timeout_s,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        result = subprocess.run(
            ["bash", str(self.script)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        return result.stdout

    def incident_lines(self, *, timeout_s: str = "60") -> list[str]:
        lines = self.stdout(timeout_s=timeout_s).splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("INCIDENTS"))
        end = next((i for i in range(start, len(lines)) if not lines[i].strip()), len(lines))
        return [line.strip() for line in lines[start + 1 : end]]


@pytest.fixture
def host(tmp_path: Path) -> _Host:
    return _Host(tmp_path=tmp_path)


def _verified() -> dict[str, object]:
    body = {
        "schema": 1,
        "status": "verified",
        "authorizes_current_effects": True,
        "normal_factory_proof": False,
        "result": {},
    }
    return {"rc": 0, "body": body}


def _refused(*, code: str) -> dict[str, object]:
    return {"rc": _REFUSED, "body": _refusal(code=code)}


def test_the_incidents_section_prints_after_the_holds_section(host: _Host) -> None:
    lines = host.stdout().splitlines()
    holds = next(i for i, line in enumerate(lines) if line.startswith("HOLDS"))
    incidents = next(i for i, line in enumerate(lines) if line.startswith("INCIDENTS"))
    assert holds < incidents


def test_a_repository_with_no_incident_entry_item_prints_none_declared(host: _Host) -> None:
    assert host.incident_lines() == ["none declared"]
    assert not host.authority_log.exists()


def test_a_missing_authority_chain_prints_entry_only_with_no_genesis(host: _Host) -> None:
    host.set_items(items=["livespec-dev-tooling-aaaaaa"])
    host.set_replies(
        replies={"livespec-dev-tooling-aaaaaa": _refused(code="incident-authority-missing")}
    )
    (line,) = host.incident_lines()
    assert line.startswith("livespec-dev-tooling-aaaaaa ")
    assert _ENTRY_ONLY in line
    assert _RECORD not in line


@pytest.mark.parametrize(
    "reply",
    [_verified(), _refused(code="incident-authority-identity-mismatch")],
    ids=["a reading", "identity-mismatch"],
)
def test_a_reading_or_an_identity_mismatch_prints_record_exists(
    host: _Host, reply: dict[str, object]
) -> None:
    host.set_items(items=["livespec-dev-tooling-bbbbbb"])
    host.set_replies(replies={"livespec-dev-tooling-bbbbbb": reply})
    (line,) = host.incident_lines()
    assert line.startswith("livespec-dev-tooling-bbbbbb ")
    assert line.endswith(_RECORD)
    assert "entry-only" not in line


@pytest.mark.parametrize(
    "code",
    [
        "incident-authority-ambiguous",
        "incident-authority-invalid-genesis",
        "incident-authority-unavailable",
    ],
)
def test_any_other_refusal_prints_unreadable_followed_by_its_code(host: _Host, code: str) -> None:
    host.set_items(items=["livespec-dev-tooling-cccccc"])
    host.set_replies(replies={"livespec-dev-tooling-cccccc": _refused(code=code)})
    (line,) = host.incident_lines()
    assert f"{_UNREADABLE} {code}" in line
    assert _RECORD not in line
    assert "entry-only" not in line


def test_a_reply_that_cannot_be_read_prints_unreadable_and_never_a_record(host: _Host) -> None:
    host.set_items(items=["livespec-dev-tooling-dddddd"])
    host.set_replies(
        replies={"livespec-dev-tooling-dddddd": {"rc": 3, "body": {"status": "verified"}}}
    )
    (line,) = host.incident_lines()
    assert f"{_UNREADABLE} incident-authority-exit" in line
    assert _RECORD not in line
    assert "entry-only" not in line


def test_a_call_that_times_out_prints_unreadable_and_never_a_record(host: _Host) -> None:
    host.set_items(items=["livespec-dev-tooling-eeeeee"])
    host.set_replies(replies={"livespec-dev-tooling-eeeeee": {"hang": True}})
    (line,) = host.incident_lines(timeout_s="1")
    assert f"{_UNREADABLE} incident-authority-timeout" in line
    assert _RECORD not in line
    assert "entry-only" not in line


def test_a_launch_exception_prints_unavailable_with_its_class_and_message(host: _Host) -> None:
    host.set_items(items=["livespec-dev-tooling-ffffff"])
    host.authority.unlink()
    (line,) = host.incident_lines()
    assert f"{_UNREADABLE} incident-authority-unavailable" in line
    assert "FileNotFoundError" in line
    assert str(host.authority) in line
    assert _RECORD not in line
    assert "entry-only" not in line


def test_each_item_is_read_on_its_own_reply(host: _Host) -> None:
    host.set_items(items=["livespec-dev-tooling-aaaaaa", "livespec-dev-tooling-bbbbbb"])
    host.set_replies(
        replies={
            "livespec-dev-tooling-aaaaaa": _refused(code="incident-authority-missing"),
            "livespec-dev-tooling-bbbbbb": _verified(),
        }
    )
    first, second = host.incident_lines()
    assert _ENTRY_ONLY in first
    assert second.endswith(_RECORD)


def test_a_top5_run_calls_only_the_read_actions_and_lists_the_ledger_once(host: _Host) -> None:
    host.set_items(items=["livespec-dev-tooling-aaaaaa", "livespec-dev-tooling-bbbbbb"])
    host.set_replies(
        replies={
            "livespec-dev-tooling-aaaaaa": _refused(code="incident-authority-missing"),
            "livespec-dev-tooling-bbbbbb": _verified(),
        }
    )
    _ = host.incident_lines()
    authority_calls = host.authority_log.read_text(encoding="utf-8").splitlines()
    assert len(authority_calls) == 2
    assert all(call.split()[0] == "read-current" for call in authority_calls)
    incident_reads = [
        call
        for call in host.ledger_log.read_text(encoding="utf-8").splitlines()
        if "incident:entry" in call
    ]
    assert incident_reads == ["bd list --label incident:entry --limit 0 --json"]
    writes = [
        call
        for call in host.ledger_log.read_text(encoding="utf-8").splitlines()
        if call.split()[1:2] in (["create"], ["update"], ["comment"], ["close"], ["label"])
    ]
    assert writes == []
