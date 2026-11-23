"""Executable coverage for the tmpfs and capacity extensions to retention."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path

import pytest

from tests.hang_guard import HANG_GUARD_SECONDS, run_under_hang_guard

_ROOT = Path(__file__).resolve().parents[2]
_ROLE = _ROOT / "ansible" / "roles" / "dev_host_retention"
_RETENTION = _ROLE / "files" / "dev-host-retention.sh"
_SCRATCH = _ROLE / "files" / "dev-host-retention-scratch.sh"
_SCRATCH_ONLY_RETENTION = _ROLE / "files" / "dev-host-retention-scratch-only.sh"
_SCRATCH_ONLY_TIMER = _ROLE / "templates" / "livespec-dev-host-retention-scratch.timer.j2"
_CAPACITY = _ROLE / "files" / "dev-host-capacity-check.sh"
_CAPACITY_TIMER = _ROLE / "templates" / "livespec-dev-host-capacity-check.timer.j2"
# The retention period and the ages straddle it by an hour each way, so a run
# slowed by host load cannot age a "new" directory past the period mid-run.
_SCRATCH_RETENTION_SECONDS = 3600
_AGED_SECONDS = 2 * _SCRATCH_RETENTION_SECONDS


def _age(*, path: Path, seconds: int) -> None:
    then = time.time() - seconds
    os.utime(path, (then, then))


def _stub(*, directory: Path, name: str, body: str) -> None:
    target = directory / name
    target.write_text(body, encoding="utf-8")
    target.chmod(0o755)


def _tmp_consumers(*, tmp_root: Path, bulk: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
    dead = tmp_root / "claude-1000" / "project" / "dead"
    live = tmp_root / "claude-1000" / "project" / "live"
    old_pytest = tmp_root / "pytest-of-ubuntu" / "pytest-1"
    new_pytest = tmp_root / "pytest-of-ubuntu" / "pytest-2"
    for directory in (dead, live, old_pytest, new_pytest):
        directory.mkdir(parents=True)
    _age(path=dead, seconds=_AGED_SECONDS)
    _age(path=live, seconds=_AGED_SECONDS)
    _age(path=old_pytest, seconds=_AGED_SECONDS)
    oldest = bulk / "oldest.dump"
    newest = bulk / "newest.dump"
    oldest.write_bytes(b"1234")
    newest.write_bytes(b"5678")
    _age(path=oldest, seconds=20)
    return dead, live, old_pytest, new_pytest, oldest, newest


def _mount_of(*, path: Path) -> str:
    """The mount `path` resolves to, as the script's own `findmnt` check reads it."""
    argv = ["findmnt", "-no", "TARGET,FSTYPE", "-T", str(path)]
    return (
        subprocess.run(argv, capture_output=True, check=False, text=True).stdout
        if shutil.which("findmnt")
        else ""
    )


def _on_root_filesystem(*, candidates: tuple[Path, ...]) -> Path:
    """The first candidate on the root filesystem, where the script requires bulk dumps.

    The script refuses a bulk-dump directory on any other mount. Which scratch
    directory qualifies differs by host: pytest's base temp is under a tmpfs
    /tmp on the dev host, and the checkout is on a separate volume in a gate
    pod. Without `findmnt` the script skips the check, so any candidate does.
    Neither candidate qualifying FAILS the test, so the bulk cap is never left
    untested in a venue.
    """
    root = _mount_of(path=Path("/"))
    mounts = {candidate: _mount_of(path=candidate) for candidate in candidates}
    chosen = next((candidate for candidate, mount in mounts.items() if mount == root), None)
    assert (
        chosen is not None
    ), f"no bulk-dump candidate is on the root filesystem ({root.strip()!r}): {mounts!r}"
    return chosen


def _hermetic_env(*, tmp_path: Path, tmp_root: Path, bulk: Path) -> dict[str, str]:
    """The run's environment, confined to the test's own directories.

    Without the checkout-root and uv-cache overrides the script sweeps every
    real checkout under /data/projects and walks the invoking user's real uv
    cache, which made the run load-sensitive and let it touch real state.
    Without the state-directory override the ownership walk writes its stamp
    under /var/lib/livespec-dev-host-retention, which a converged host holds
    root-owned, so the write is refused and the run fails.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(directory=bin_dir, name="docker", body="#!/bin/sh\nexit 0\n")
    _stub(directory=bin_dir, name="uv", body="#!/bin/sh\nexit 0\n")
    checkout_roots = tmp_path / "checkouts"
    checkout_roots.mkdir()
    uv_cache = tmp_path / "uv-cache"
    uv_cache.mkdir()
    return os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "LIVESPEC_DEV_HOST_TMP_ROOT": str(tmp_root),
        "LIVESPEC_DEV_HOST_SCRATCH_RETENTION_SECONDS": str(_SCRATCH_RETENTION_SECONDS),
        "LIVESPEC_DEV_HOST_BULK_DUMP_DIR": str(bulk),
        "LIVESPEC_DEV_HOST_BULK_DUMP_CAP_BYTES": "4",
        "LIVESPEC_DEV_HOST_RETENTION_USER": str(os.getuid()),
        "LIVESPEC_DEV_HOST_RETENTION_CHECKOUT_ROOTS": str(checkout_roots),
        "LIVESPEC_DEV_HOST_UV_CACHE_DIR": str(uv_cache),
        "LIVESPEC_DEV_HOST_RETENTION_STATE_DIR": str(tmp_path / "state"),
    }


def test_scratch_only_retention_removes_dead_scratch_and_fires_every_two_hours(
    *, tmp_path: Path
) -> None:
    """The frequent run keeps live Claude scratch while reclaiming dead scratch and pytest.

    This is deliberately driven through the scratch-only entry point, rather
    than the daily retention script: a two-hour run must not pay for docker,
    uv, gate-run, marketplace-backup, or bulk-dump retention.
    """
    assert _SCRATCH_ONLY_RETENTION.is_file(), (
        "the role must ship a scratch-and-pytest-only retention entry point for "
        "the frequent timer"
    )
    tmp_root = tmp_path / "tmp"
    dead = tmp_root / "claude-1000" / "project" / "dead"
    live = tmp_root / "claude-1000" / "project" / "live"
    old_pytest = tmp_root / "pytest-of-ubuntu" / "pytest-1"
    for directory in (dead, live, old_pytest):
        directory.mkdir(parents=True)
        _age(path=directory, seconds=_AGED_SECONDS)
    proc_root = tmp_path / "proc"
    environment = proc_root / "100" / "environ"
    environment.parent.mkdir(parents=True)
    environment.write_bytes(b"CLAUDE_CODE_SESSION_ID=live\0")

    done = subprocess.run(
        ["bash", str(_SCRATCH_ONLY_RETENTION)],
        env=_hermetic_env(tmp_path=tmp_path, tmp_root=tmp_root, bulk=tmp_path / "bulk")
        | {"LIVESPEC_DEV_HOST_RETENTION_PROC_ROOT": str(proc_root)},
        capture_output=True,
        check=False,
        text=True,
    )

    assert done.returncode == 0, done.stdout + done.stderr
    assert not dead.exists(), done.stdout
    assert live.exists(), done.stdout
    assert not old_pytest.exists(), done.stdout
    assert "free space before:" in done.stdout and "free space after:" in done.stdout, done.stdout

    timer = _SCRATCH_ONLY_TIMER.read_text(encoding="utf-8")
    assert "OnBootSec=2min" in timer
    assert "OnUnitActiveSec={{ dev_host_retention_scratch_on_unit_active_sec }}" in timer
    assert "Unit={{ dev_host_retention_scratch_service }}" in timer
    defaults = (_ROLE / "defaults" / "main.yml").read_text(encoding="utf-8")
    assert "dev_host_retention_scratch_on_unit_active_sec: 2h" in defaults
    assert "dev_host_retention_scratch_on_unit_active_sec" in (_ROLE / "HOST_VARS.md").read_text(
        encoding="utf-8"
    )


def test_retention_keeps_a_live_session_when_an_environment_cannot_be_read(
    *, tmp_path: Path
) -> None:
    """An unreadable process environment must be silent and not stop liveness discovery."""
    assert _SCRATCH.is_file(), "the committed scratch helper must implement liveness discovery"
    tmp_root = tmp_path / "tmp"
    live = tmp_root / "claude-1000" / "project" / "live"
    dead = tmp_root / "claude-1000" / "project" / "dead"
    for session in (live, dead):
        session.mkdir(parents=True)
        _age(path=session, seconds=_AGED_SECONDS)
    proc_root = tmp_path / "proc"
    live_environment = proc_root / "100" / "environ"
    live_environment.parent.mkdir(parents=True)
    live_environment.write_bytes(b"CLAUDE_CODE_SESSION_ID=live\0")
    # Reading a directory as an environment fails like a disappeared /proc file.
    (proc_root / "101" / "environ").mkdir(parents=True)
    bulk = tmp_path / "bulk"

    done = subprocess.run(
        ["bash", str(_RETENTION)],
        env=_hermetic_env(tmp_path=tmp_path, tmp_root=tmp_root, bulk=bulk)
        | {"LIVESPEC_DEV_HOST_RETENTION_PROC_ROOT": str(proc_root)},
        capture_output=True,
        check=False,
        text=True,
    )

    assert done.returncode == 0, done.stdout + done.stderr
    assert live.exists(), done.stdout
    assert not dead.exists(), done.stdout
    assert done.stderr == ""


def test_retention_removes_no_session_scratch_when_no_environment_can_be_read(
    *, tmp_path: Path
) -> None:
    """A scan that read no environment at all is not a scan that found no live session.

    xargs exits 123 when every grep exits 2, the same status as a scan whose
    greps merely found no match, so an unreadable process root would otherwise
    make every aged session look dead. The session leg is skipped with a
    WARNING and the pytest leg, which does not depend on liveness, still runs.
    """
    assert _SCRATCH.is_file(), "the committed scratch helper must implement liveness discovery"
    tmp_root = tmp_path / "tmp"
    session = tmp_root / "claude-1000" / "project" / "unreadable"
    old_pytest = tmp_root / "pytest-of-ubuntu" / "pytest-1"
    for directory in (session, old_pytest):
        directory.mkdir(parents=True)
        _age(path=directory, seconds=_AGED_SECONDS)
    proc_root = tmp_path / "proc"
    # Reading a directory as an environment fails like an unreadable /proc file.
    for pid in ("100", "101"):
        (proc_root / pid / "environ").mkdir(parents=True)

    done = run_under_hang_guard(
        ["bash", str(_RETENTION)],
        env=_hermetic_env(tmp_path=tmp_path, tmp_root=tmp_root, bulk=tmp_path / "bulk")
        | {"LIVESPEC_DEV_HOST_RETENTION_PROC_ROOT": str(proc_root)},
        capture_output=True,
        check=False,
        text=True,
    )

    assert done.returncode == 0, done.stdout + done.stderr
    assert session.exists(), done.stdout
    assert "session leg skipped: liveness scan failed" in done.stdout, done.stdout
    assert not old_pytest.exists(), done.stdout


@pytest.mark.integration
def test_retention_keeps_sessions_held_by_process_cwd_or_file_descriptor(*, tmp_path: Path) -> None:
    """A process holding scratch keeps its session without an environment carrier.

    The fixture process root represents the Claude process itself: neither
    process carries a session-id environment entry, one has an fd below its
    scratch directory, and the other has its cwd at its scratch directory.
    A peer with neither signal remains removable.
    """
    assert _SCRATCH.is_file(), "the committed scratch helper must implement liveness discovery"
    tmp_root = tmp_path / "tmp"
    held_by_fd = tmp_root / "claude-1000" / "project" / "held-by-fd"
    held_by_cwd = tmp_root / "claude-1000" / "project" / "held-by-cwd"
    dead = tmp_root / "claude-1000" / "project" / "dead"
    for session in (held_by_fd, held_by_cwd, dead):
        session.mkdir(parents=True)
    held_file = held_by_fd / "tasks" / "output.txt"
    held_file.parent.mkdir()
    held_file.write_text("held", encoding="utf-8")
    # Age after creating the fd target: adding `tasks` refreshes the session mtime.
    for session in (held_by_fd, held_by_cwd, dead):
        _age(path=session, seconds=_AGED_SECONDS)
    proc_root = tmp_path / "proc"
    for pid in ("100", "101", "102"):
        environment = proc_root / pid / "environ"
        environment.parent.mkdir(parents=True)
        environment.write_bytes(b"HOME=/home/fixture\0")
    fd = proc_root / "100" / "fd" / "3"
    fd.parent.mkdir()
    fd.symlink_to(held_file)
    cwd = proc_root / "101" / "cwd"
    cwd.symlink_to(held_by_cwd)
    # A vanished cwd and unreadable fd directory are silent, like an
    # unreadable environment in the existing liveness test.
    (proc_root / "102" / "cwd").symlink_to(tmp_path / "vanished")
    (proc_root / "102" / "fd").mkdir()

    done = subprocess.run(
        ["bash", str(_RETENTION)],
        env=_hermetic_env(tmp_path=tmp_path, tmp_root=tmp_root, bulk=tmp_path / "bulk")
        | {"LIVESPEC_DEV_HOST_RETENTION_PROC_ROOT": str(proc_root)},
        capture_output=True,
        check=False,
        text=True,
    )

    assert done.returncode == 0, done.stdout + done.stderr
    assert held_by_fd.exists(), done.stdout
    assert held_by_cwd.exists(), done.stdout
    assert not dead.exists(), done.stdout
    assert f"removed dead session scratch {dead}" in done.stdout
    assert done.stderr == ""


def _exec_counting_path(*, shim_dir: Path, path: str, log: Path) -> str:
    """A PATH whose every command records one line in `log` before it runs.

    Each executable name the run could resolve gets a shim that appends its
    name and then execs the real binary, so the log holds one line per child
    process the run starts through PATH, whatever the command.
    """
    shim_dir.mkdir()
    seen: set[str] = set()
    for directory in path.split(os.pathsep):
        # `glob` yields nothing for a PATH entry that does not exist.
        for entry in sorted(Path(directory).glob("*")):
            if entry.name in seen or not entry.is_file() or not os.access(entry, os.X_OK):
                continue
            seen.add(entry.name)
            _stub(
                directory=shim_dir,
                name=entry.name,
                body=f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(entry.name)} >> \"$EXEC_LOG\"\n"
                f'exec {shlex.quote(str(entry))} "$@"\n',
            )
    log.touch()
    return f"{shim_dir}{os.pathsep}{path}"


def _run_over_process_root(*, base: Path, process_count: int) -> tuple[Path, Path, Path, list[str]]:
    """One retention run over a fixture process root of `process_count` entries.

    Two of the entries carry a live session id, the rest carry other
    variables. Returns the two live session directories, the dead one, and
    the commands the run started.
    """
    base.mkdir()
    tmp_root = base / "tmp"
    sessions = {
        name: tmp_root / "claude-1000" / "project" / name
        for name in ("live-one", "live-two", "dead")
    }
    for session in sessions.values():
        session.mkdir(parents=True)
        _age(path=session, seconds=_AGED_SECONDS)
    proc_root = base / "proc"
    for pid in range(100, 100 + process_count):
        environment = proc_root / str(pid) / "environ"
        environment.parent.mkdir(parents=True)
        environment.write_bytes(f"HOME=/home/u{pid}\0PATH=/usr/bin\0".encode())
    for pid, session_id in ((100, "live-one"), (101 + process_count // 2, "live-two")):
        (proc_root / str(pid) / "environ").write_bytes(
            f"PWD=/\0CLAUDE_CODE_SESSION_ID={session_id}\0TERM=dumb\0".encode()
        )
    exec_log = base / "exec.log"
    environment = _hermetic_env(tmp_path=base, tmp_root=tmp_root, bulk=base / "bulk")
    environment["PATH"] = _exec_counting_path(
        shim_dir=base / "exec-shims", path=environment["PATH"], log=exec_log
    )
    environment |= {
        "LIVESPEC_DEV_HOST_RETENTION_PROC_ROOT": str(proc_root),
        "EXEC_LOG": str(exec_log),
    }
    bash = shutil.which("bash")
    assert bash is not None

    done = run_under_hang_guard(
        [bash, str(_RETENTION)],
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert done.returncode == 0, done.stdout + done.stderr
    started = exec_log.read_text(encoding="utf-8").splitlines()
    return sessions["live-one"], sessions["live-two"], sessions["dead"], started


def test_retention_scans_liveness_with_a_fixed_number_of_child_processes(*, tmp_path: Path) -> None:
    """The live-session scan's child processes do not grow with the process count.

    One child per process made the scan take 34 s over 1,076 processes at load
    46 on the dev host (livespec-dev-tooling-spva5x). A run over 2,000 process
    entries must start exactly as many child processes as a run over 20, and
    still keep every live session and remove the aged dead one.
    """
    assert _SCRATCH.is_file(), "the committed scratch helper must implement liveness discovery"
    small = _run_over_process_root(base=tmp_path / "small", process_count=20)
    large = _run_over_process_root(base=tmp_path / "large", process_count=2000)

    for live_one, live_two, dead, _ in (small, large):
        assert live_one.exists()
        assert live_two.exists()
        assert not dead.exists()
    assert Counter(large[3]) == Counter(small[3]), (
        f"20 entries started {len(small[3])} child processes, 2,000 started {len(large[3])}; "
        f"only at 2,000: {Counter(large[3]) - Counter(small[3])}, "
        f"only at 20: {Counter(small[3]) - Counter(large[3])}"
    )


def test_retention_removes_no_session_scratch_when_the_liveness_scan_cannot_run(
    *, tmp_path: Path
) -> None:
    """A liveness scan that did not complete removes no session directory.

    An empty answer from a scan that never ran would make every session look
    dead. The session leg is skipped with a WARNING naming the scan's status,
    and the pytest leg, which does not depend on liveness, still runs.
    """
    assert _SCRATCH.is_file(), "the committed scratch helper must implement liveness discovery"
    tmp_root = tmp_path / "tmp"
    session = tmp_root / "claude-1000" / "project" / "unscanned"
    old_pytest = tmp_root / "pytest-of-ubuntu" / "pytest-1"
    for directory in (session, old_pytest):
        directory.mkdir(parents=True)
        _age(path=directory, seconds=_AGED_SECONDS)
    proc_root = tmp_path / "proc"
    environment_file = proc_root / "100" / "environ"
    environment_file.parent.mkdir(parents=True)
    environment_file.write_bytes(b"CLAUDE_CODE_SESSION_ID=other\0")
    environment = _hermetic_env(tmp_path=tmp_path, tmp_root=tmp_root, bulk=tmp_path / "bulk")
    # xargs exits 127 when the command it runs cannot be found.
    _stub(directory=tmp_path / "bin", name="xargs", body="#!/bin/sh\nexit 127\n")
    environment["LIVESPEC_DEV_HOST_RETENTION_PROC_ROOT"] = str(proc_root)

    done = run_under_hang_guard(
        ["bash", str(_RETENTION)],
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert done.returncode == 0, done.stdout + done.stderr
    assert session.exists(), done.stdout
    assert "session leg skipped: liveness scan failed (status 127)" in done.stdout, done.stdout
    assert not old_pytest.exists(), done.stdout


def test_retention_reclaims_dead_tmp_scratch_pytest_and_oldest_bulk_dumps(
    *, tmp_path: Path
) -> None:
    """One run keeps a live session but bounds every new tmpfs consumer."""
    assert _RETENTION.is_file(), "the committed retention script must implement tmpfs cleanup"
    tmp_root = tmp_path / "tmp"
    (_ROOT / "tmp").mkdir(exist_ok=True)
    bulk = Path(
        tempfile.mkdtemp(
            prefix="retention-bulk-",
            dir=_on_root_filesystem(candidates=(tmp_path, _ROOT / "tmp")),
        )
    )
    dead, live, old_pytest, new_pytest, oldest, newest = _tmp_consumers(
        tmp_root=tmp_root, bulk=bulk
    )

    # The live session's process must outlive the run however slow the host
    # is; it is terminated as soon as the run returns.
    child = subprocess.Popen(["sleep", "600"], env=os.environ | {"CLAUDE_CODE_SESSION_ID": "live"})
    try:
        done = run_under_hang_guard(
            ["bash", str(_RETENTION)],
            env=_hermetic_env(tmp_path=tmp_path, tmp_root=tmp_root, bulk=bulk),
            capture_output=True,
            check=False,
            text=True,
        )
    finally:
        child.terminate()
        _ = child.wait(HANG_GUARD_SECONDS)
        bulk_left = {path.name for path in bulk.iterdir()}
        shutil.rmtree(bulk)

    assert done.returncode == 0, done.stdout + done.stderr
    assert not dead.exists(), done.stdout
    assert live.exists(), done.stdout
    assert not old_pytest.exists(), done.stdout
    assert new_pytest.exists(), done.stdout
    assert oldest.name not in bulk_left, "the bulk cap must remove the oldest file first"
    assert newest.name in bulk_left, "the cap must not remove newer files before older files"
    assert "free space before:" in done.stdout and "/tmp" in done.stdout
    assert "free space after:" in done.stdout


def test_retention_caps_two_thousand_bulk_dumps_with_fixed_directory_walks(
    *, tmp_path: Path
) -> None:
    """Capping 1,000 dumps walks the bulk directory a fixed number of times.

    The fixture uses one-byte files and a deterministic total of 2,000 bytes,
    requiring removal of precisely the oldest half. The bulk `find` shim only
    serves its real listing once: a legacy second listing becomes empty and
    fails quickly on the excess command count, while a one-listing
    implementation still processes all 2,000 real files.
    """
    assert _RETENTION.is_file(), "the committed retention script must implement bulk capping"
    (_ROOT / "tmp").mkdir(exist_ok=True)
    bulk = Path(
        tempfile.mkdtemp(
            prefix="retention-bulk-fixed-walks-",
            dir=_on_root_filesystem(candidates=(tmp_path, _ROOT / "tmp")),
        )
    )
    for index in range(2000):
        dump = bulk / f"dump-{index:04d}.jsonl"
        dump.write_bytes(b"x")
        os.utime(dump, ns=(1_000_000_000 + index, 1_000_000_000 + index))
    exec_log = tmp_path / "exec.log"
    environment = _hermetic_env(tmp_path=tmp_path, tmp_root=tmp_path / "tmp", bulk=bulk)
    environment["PATH"] = _exec_counting_path(
        shim_dir=tmp_path / "exec-shims", path=environment["PATH"], log=exec_log
    )
    environment["EXEC_LOG"] = str(exec_log)
    environment["LIVESPEC_DEV_HOST_UV_CACHE_DIR"] = str(tmp_path / "missing-uv-cache")
    _stub(
        directory=tmp_path / "exec-shims",
        name="du",
        body="#!/bin/sh\nprintf '%s\\n' du >> \"$EXEC_LOG\"\nprintf '2000\\t%s\\n' \"$3\"\n",
    )
    real_find = shutil.which("find")
    assert real_find is not None
    bulk_find_state = tmp_path / "bulk-find-seen"
    _stub(
        directory=tmp_path / "exec-shims",
        name="find",
        body=(
            "#!/bin/sh\nprintf '%s\\n' find >> \"$EXEC_LOG\"\n"
            f'if [ "$1" = {shlex.quote(str(bulk))} ]; then\n'
            f"    if [ -e {shlex.quote(str(bulk_find_state))} ]; then exit 0; fi\n"
            f"    : > {shlex.quote(str(bulk_find_state))}\n"
            "fi\n"
            f'exec {shlex.quote(real_find)} "$@"\n'
        ),
    )
    environment["LIVESPEC_DEV_HOST_BULK_DUMP_CAP_BYTES"] = "1000"

    try:
        done = run_under_hang_guard(
            ["bash", str(_RETENTION)],
            env=environment,
            capture_output=True,
            check=False,
            text=True,
        )
        remaining = {path.name for path in bulk.iterdir()}
    finally:
        shutil.rmtree(bulk)

    assert done.returncode == 0, done.stdout + done.stderr
    started = Counter(exec_log.read_text(encoding="utf-8").splitlines())
    assert started["du"] == 1 and started["find"] == 2, (
        "a 2,000-file bulk cap must start one du and one bulk find, plus the "
        f"liveness find; started {started['du']} du and {started['find']} find processes"
    )
    assert remaining == {f"dump-{index:04d}.jsonl" for index in range(1000, 2000)}


def test_retention_bulk_cap_counts_a_vanished_snapshot_file_against_the_total(
    *, tmp_path: Path
) -> None:
    """A snapshot file that vanished is logged, skipped, and still leaves the total.

    The directory shrank by the vanished file's recorded size, so the cap must
    subtract it and stop once the remaining files fit, rather than removing a
    newer file the cap no longer requires removing.
    """
    assert _RETENTION.is_file(), "the committed retention script must implement bulk capping"
    (_ROOT / "tmp").mkdir(exist_ok=True)
    bulk = Path(
        tempfile.mkdtemp(
            prefix="retention-bulk-vanished-",
            dir=_on_root_filesystem(candidates=(tmp_path, _ROOT / "tmp")),
        )
    )
    for index in range(10):
        dump = bulk / f"dump-{index:02d}.bin"
        dump.write_bytes(b"x" * 100)
        os.utime(dump, ns=(1_000_000_000 + index, 1_000_000_000 + index))
    environment = _hermetic_env(tmp_path=tmp_path, tmp_root=tmp_path / "tmp", bulk=bulk)
    shim_dir = tmp_path / "vanish-shims"
    shim_dir.mkdir()
    environment["PATH"] = f"{shim_dir}{os.pathsep}{environment['PATH']}"
    environment["LIVESPEC_DEV_HOST_UV_CACHE_DIR"] = str(tmp_path / "missing-uv-cache")
    # The measured total still counts the 300-byte file listed in the snapshot
    # that is gone by the time the loop reaches it.
    _stub(
        directory=shim_dir,
        name="du",
        body="#!/bin/sh\nprintf '1300\\t%s\\n' \"$3\"\n",
    )
    real_find = shutil.which("find")
    assert real_find is not None
    gone = bulk / "dump-gone.bin"
    _stub(
        directory=shim_dir,
        name="find",
        body=(
            "#!/bin/sh\n"
            f'if [ "$1" = {shlex.quote(str(bulk))} ]; then\n'
            f"    printf '1:300:%s\\0' {shlex.quote(str(gone))}\n"
            "fi\n"
            f'exec {shlex.quote(real_find)} "$@"\n'
        ),
    )
    environment["LIVESPEC_DEV_HOST_BULK_DUMP_CAP_BYTES"] = "700"

    try:
        done = run_under_hang_guard(
            ["bash", str(_RETENTION)],
            env=environment,
            capture_output=True,
            check=False,
            text=True,
        )
        remaining = {path.name for path in bulk.iterdir()}
    finally:
        shutil.rmtree(bulk)

    assert done.returncode == 0, done.stdout + done.stderr
    assert f"skipped bulk dump {gone}: it vanished" in done.stdout, done.stdout
    assert remaining == {f"dump-{index:02d}.bin" for index in range(3, 10)}, (
        "the vanished 300 bytes count toward the cap, so exactly the three oldest "
        f"real files go; remaining {sorted(remaining)}"
    )


def test_capacity_check_alerts_tmp_once_without_alerting_root(*, tmp_path: Path) -> None:
    """The repeat state prevents a full tmpfs from paging every 15 minutes."""
    assert _CAPACITY.is_file(), "the committed capacity check must exist"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl_log = tmp_path / "curl.log"
    _stub(
        directory=bin_dir,
        name="df",
        body="#!/bin/sh\nprintf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n'\n"
        "case \"$3\" in /tmp) printf 'tmpfs 100 75 25 75%% /tmp\\n' ;; *) printf '/dev/root 100 60 40 60%% /\\n' ;; esac\n",
    )
    _stub(directory=bin_dir, name="curl", body=f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {curl_log}\n")
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "LIVESPEC_DEV_HOST_CAPACITY_STATE_DIR": str(tmp_path / "state"),
        "LIVESPEC_DEV_HOST_NTFY_TOPIC": "test-topic",
        "LIVESPEC_DEV_HOST_ROOT_THRESHOLD_PERCENT": "85",
        "LIVESPEC_DEV_HOST_TMP_THRESHOLD_PERCENT": "75",
        "LIVESPEC_DEV_HOST_CAPACITY_REPEAT_SECONDS": "3600",
    }

    first = subprocess.run(
        ["bash", str(_CAPACITY)], env=env, capture_output=True, text=True, check=False
    )
    second = subprocess.run(
        ["bash", str(_CAPACITY)], env=env, capture_output=True, text=True, check=False
    )

    assert first.returncode == second.returncode == 0
    notices = curl_log.read_text(encoding="utf-8")
    assert notices.count("/tmp") == 1
    assert "75%" in notices and "25 KiB" in notices
    assert "/ used" not in notices
    assert "OnUnitActiveSec=15min" in _CAPACITY_TIMER.read_text(encoding="utf-8")


def _capacity_env(*, tmp_path: Path, bin_dir: Path) -> dict[str, str]:
    return os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "LIVESPEC_DEV_HOST_CAPACITY_STATE_DIR": str(tmp_path / "state"),
        "LIVESPEC_DEV_HOST_NTFY_TOPIC": "test-topic",
        "LIVESPEC_DEV_HOST_ROOT_THRESHOLD_PERCENT": "85",
        "LIVESPEC_DEV_HOST_ALERT_OWNER": "owner-seat-x",
        "LIVESPEC_DEV_HOST_ALERT_RUNBOOK": "runbook/path.md",
    }


def _capacity_stubs(*, tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(
        directory=bin_dir,
        name="df",
        body="#!/bin/sh\nprintf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n'\n"
        "printf '/dev/root 100 90 10 90%% /\\n'\n",
    )
    _stub(
        directory=bin_dir,
        name="curl",
        body=f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {tmp_path / 'curl.log'}\n",
    )
    return bin_dir


def test_capacity_alert_names_owner_and_runbook_and_is_recorded_in_the_ledger(
    *, tmp_path: Path
) -> None:
    """A seat reads the alert from the epic comment; the push carries the same text."""
    bin_dir = _capacity_stubs(tmp_path=tmp_path)
    wrapper = tmp_path / "wrapper.sh"
    wrapper.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$PWD $*\" >> {tmp_path / 'ledger.log'}\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    env = _capacity_env(tmp_path=tmp_path, bin_dir=bin_dir) | {
        "LIVESPEC_DEV_HOST_ALERT_LEDGER_EPIC": "epic-1",
        "LIVESPEC_DEV_HOST_ALERT_LEDGER_DIR": str(tmp_path),
        "LIVESPEC_DEV_HOST_ALERT_LEDGER_WRAPPER": str(wrapper),
    }

    done = subprocess.run(
        ["bash", str(_CAPACITY)], env=env, capture_output=True, text=True, check=False
    )

    assert done.returncode == 0, done.stdout + done.stderr
    push = (tmp_path / "curl.log").read_text(encoding="utf-8")
    assert "Owner: owner-seat-x" in push and "Runbook: runbook/path.md" in push, push
    ledger = (tmp_path / "ledger.log").read_text(encoding="utf-8")
    assert "-- bd comment epic-1" in ledger, ledger
    assert "90%" in ledger and "owner-seat-x" in ledger and "runbook/path.md" in ledger, ledger


def test_capacity_alert_degrades_to_ntfy_with_a_warning_when_the_wrapper_is_missing(
    *, tmp_path: Path
) -> None:
    bin_dir = _capacity_stubs(tmp_path=tmp_path)
    env = _capacity_env(tmp_path=tmp_path, bin_dir=bin_dir) | {
        "LIVESPEC_DEV_HOST_ALERT_LEDGER_EPIC": "epic-1",
        "LIVESPEC_DEV_HOST_ALERT_LEDGER_DIR": str(tmp_path),
        "LIVESPEC_DEV_HOST_ALERT_LEDGER_WRAPPER": str(tmp_path / "absent-wrapper"),
    }

    done = subprocess.run(
        ["bash", str(_CAPACITY)], env=env, capture_output=True, text=True, check=False
    )

    assert done.returncode == 0, done.stdout + done.stderr
    assert "WARNING: ledger record unavailable" in done.stdout, done.stdout
    assert "Owner: owner-seat-x" in (tmp_path / "curl.log").read_text(encoding="utf-8")
