"""The CI converge trigger applies merged CI-stack changes and holds credential ranges.

Work item livespec-dev-tooling-ctete5. `apply-merged-ci-changes.sh` runs for real
against a local origin repository with the apply and drift commands faked, so the
tests read what the wrapper decided: which tags it applied with, whether it held,
and whether the last-applied SHA moved.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import yaml

__all__: list[str] = []

_REPO = Path(__file__).resolve().parents[2]
_DIR = _REPO / "ci-runner" / "converge-trigger"
_SCRIPT = _DIR / "apply-merged-ci-changes.sh"
_ROLE = _REPO / "ansible" / "roles" / "ci_converge_trigger"
_CLEAN_RECAP = "host-a : ok=3 changed=0 unreachable=0 failed=0\nhost-b : ok=3 changed=0 unreachable=0 failed=0\n"
_PLACEMENT = "ci-runner/k3s/phase2/arc/runner-node-preference.conf"
_CREDENTIAL = "ci-runner/k3s/phase2/gates/gates-rbac.yaml"
_OTHER = "ci-runner/k3s/phase2/kueue/cluster-queue-gates.yaml"


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


class _World:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.origin = tmp / "origin"
        self.origin.mkdir()
        _git(self.origin, "init", "-q", "-b", "master")
        trig = self.origin / "ci-runner" / "converge-trigger"
        trig.mkdir(parents=True)
        for name in ("credential-manifests.list", "placement-files.list"):
            shutil.copy(_DIR / name, trig / name)
        for rel in (_PLACEMENT, _CREDENTIAL, _OTHER):
            self.write(rel, "v0\n")
        self.commit("base")
        self.state = tmp / "state"
        self.apply_log = tmp / "apply.log"
        self.signal_log = tmp / "signal.log"
        self.drift_out = tmp / "drift.out"
        self.drift_out.write_text(_CLEAN_RECAP)
        (tmp / "apply.sh").write_text(
            f'#!/bin/sh\necho "$@" >>{self.apply_log}\n[ ! -e {tmp}/apply-fails ]\n'
        )
        (tmp / "drift.sh").write_text(f"#!/bin/sh\ncat {self.drift_out}\n")
        (tmp / "signal.sh").write_text(f'#!/bin/sh\necho "$@" >>{self.signal_log}\n')
        for n in ("apply.sh", "drift.sh", "signal.sh"):
            (tmp / n).chmod(0o755)

    def write(self, rel: str, text: str) -> None:
        path = self.origin / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, msg: str) -> str:
        _git(self.origin, "add", "-A")
        _git(self.origin, "commit", "-q", "-m", msg)
        return _git(self.origin, "rev-parse", "HEAD")

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.tmp),
            "CONVERGE_TRIGGER_STATE_DIR": str(self.state),
            "CONVERGE_TRIGGER_REPO_URL": str(self.origin),
            "CONVERGE_TRIGGER_APPLY_CMD": f"{self.tmp}/apply.sh",
            "CONVERGE_TRIGGER_DRIFT_CMD": f"{self.tmp}/drift.sh",
            "CONVERGE_TRIGGER_SIGNAL_CMD": f"{self.tmp}/signal.sh",
        }
        return subprocess.run(
            ["bash", str(_SCRIPT), *args], env=env, capture_output=True, text=True, check=False
        )

    def last(self) -> str:
        return (self.state / "last-applied-sha").read_text().strip()

    def applies(self) -> list[str]:
        return self.apply_log.read_text().splitlines() if self.apply_log.exists() else []

    def signals(self) -> list[str]:
        return self.signal_log.read_text().splitlines() if self.signal_log.exists() else []


def test_an_unseeded_trigger_applies_nothing(tmp_path: Path) -> None:
    w = _World(tmp_path)
    assert w.run().returncode == 3
    assert w.applies() == []


def test_a_placement_only_range_applies_with_the_placement_tag_and_moves_the_sha(
    tmp_path: Path,
) -> None:
    w = _World(tmp_path)
    base = _git(w.origin, "rev-parse", "HEAD")
    w.run("--seed", base)
    w.write(_PLACEMENT, "v1\n")
    tip = w.commit("weight")
    assert w.run().returncode == 0
    assert w.applies() == ["--tags ci_placement"]
    assert w.last() == tip


def test_any_other_ci_stack_path_applies_with_the_full_converge_tag(tmp_path: Path) -> None:
    w = _World(tmp_path)
    w.run("--seed", _git(w.origin, "rev-parse", "HEAD"))
    w.write(_PLACEMENT, "v1\n")
    w.write(_OTHER, "v1\n")
    w.commit("mixed")
    assert w.run().returncode == 0
    assert w.applies() == ["--tags ci_converge_unit"]


def test_a_range_without_a_ci_stack_path_advances_without_applying(tmp_path: Path) -> None:
    w = _World(tmp_path)
    w.run("--seed", _git(w.origin, "rev-parse", "HEAD"))
    w.write("docs/x.md", "x\n")
    tip = w.commit("docs")
    assert w.run().returncode == 0
    assert w.applies() == []
    assert w.last() == tip


def test_a_credential_manifest_holds_the_whole_range_and_signals_once(tmp_path: Path) -> None:
    w = _World(tmp_path)
    base = _git(w.origin, "rev-parse", "HEAD")
    w.run("--seed", base)
    w.write(_PLACEMENT, "v1\n")
    w.write(_CREDENTIAL, "v1\n")
    w.commit("carries a credential file")
    assert w.run().returncode == 4
    assert w.run().returncode == 4
    assert w.applies() == []
    assert w.last() == base
    assert len(w.signals()) == 1
    assert _CREDENTIAL in w.signals()[0]


def test_a_failed_apply_keeps_the_sha_and_the_third_failure_signals(tmp_path: Path) -> None:
    w = _World(tmp_path)
    base = _git(w.origin, "rev-parse", "HEAD")
    w.run("--seed", base)
    w.write(_PLACEMENT, "v1\n")
    w.commit("weight")
    (tmp_path / "apply-fails").write_text("")
    codes = [w.run().returncode for _ in range(3)]
    assert codes == [1, 1, 1]
    assert w.last() == base
    assert len(w.signals()) == 1
    (tmp_path / "apply-fails").unlink()
    assert w.run().returncode == 0
    assert len(w.signals()) == 2


def test_a_read_back_that_is_not_zero_fails_the_apply(tmp_path: Path) -> None:
    w = _World(tmp_path)
    base = _git(w.origin, "rev-parse", "HEAD")
    w.run("--seed", base)
    w.write(_PLACEMENT, "v1\n")
    w.commit("weight")
    w.drift_out.write_text("host-a : ok=3 changed=2 unreachable=0 failed=0\n")
    assert w.run().returncode == 1
    assert w.last() == base


def test_the_kill_switch_stops_a_tick_before_anything_runs(tmp_path: Path) -> None:
    w = _World(tmp_path)
    base = _git(w.origin, "rev-parse", "HEAD")
    w.run("--seed", base)
    w.write(_PLACEMENT, "v1\n")
    w.commit("weight")
    (w.state / "apply.disabled").write_text("")
    assert w.run().returncode == 0
    assert w.applies() == []
    assert w.last() == base


def test_the_placement_list_equals_the_roles_placement_files() -> None:
    defaults = yaml.safe_load(
        (_REPO / "ansible" / "roles" / "ci_converge_unit" / "defaults" / "main.yml").read_text(),
    )
    expected = {
        f"ci-runner/k3s/phase2/{e['src']}" for e in defaults["ci_converge_unit_placement_files"]
    }
    listed = {
        line.strip()
        for line in (_DIR / "placement-files.list").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert listed == expected


def test_every_credential_manifest_path_exists_and_every_secret_manifest_is_listed() -> None:
    entries = [
        line.strip()
        for line in (_DIR / "credential-manifests.list").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    for entry in entries:
        assert (_REPO / entry).exists(), entry
    for manifest in (_REPO / "ci-runner").rglob("*.yaml"):
        rel = manifest.relative_to(_REPO).as_posix()
        if "kind: Secret" in manifest.read_text() and "stringData" in manifest.read_text():
            assert any(rel == e or (e.endswith("/") and rel.startswith(e)) for e in entries), rel


def test_the_trigger_names_no_machine_and_the_play_installs_it_after_the_identity_guard() -> None:
    for path in [*_DIR.iterdir(), *_ROLE.rglob("*.yml")]:
        text = path.read_text()
        for host in ("hetzner", "vps", "gmktec", "poweredge", "hp-xubuntu", "gamingpc"):
            assert host not in text, (path, host)
    play = yaml.safe_load((_REPO / "ansible" / "control-node.yml").read_text())[0]
    assert "roles" not in play
    names = [t.get("name") for t in play["tasks"]]
    assert names.index("Install the CI converge trigger") > 0
