"""Integration coverage for the dev-host retention worktree report.

The report is deliberately observational: a linked worktree can be clean and
merged while its owner is about to resume work there.  The retention run may
identify that disk use, but it must never remove the worktree.
"""

from __future__ import annotations

import os
import pwd
import subprocess
import time
from pathlib import Path

import pytest

from tests.hang_guard import run_under_hang_guard

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "ansible/roles/dev_host_retention/files/dev-host-retention.sh"


def _git(*args: str, cwd: Path | None = None) -> str:
    """Run git in the fixture repository and return its standard output."""
    done = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def _linked_worktrees(*, tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create one reportable worktree and two worktrees the report must skip."""
    remote = tmp_path / "remote.git"
    primary = tmp_path / "primary"
    worktree_root = tmp_path / "home" / ".worktrees" / "repo"
    _git("init", "--bare", "--quiet", str(remote))
    _git("init", "--initial-branch=master", "--quiet", str(primary))
    _git("config", "user.name", "Retention test", cwd=primary)
    _git("config", "user.email", "retention-test@example.invalid", cwd=primary)
    _ = (primary / "README").write_text("base\n", encoding="utf-8")
    _git("add", "README", cwd=primary)
    _git("commit", "--quiet", "-m", "base", cwd=primary)
    _git("remote", "add", "origin", str(remote), cwd=primary)
    _git("push", "--quiet", "-u", "origin", "master", cwd=primary)

    merged = worktree_root / "reportable"
    dirty = worktree_root / "dirty"
    unmerged = worktree_root / "unmerged"
    _git(
        "worktree", "add", "--quiet", "-b", "reportable", str(merged), "origin/master", cwd=primary
    )
    _git("worktree", "add", "--quiet", "-b", "dirty", str(dirty), "origin/master", cwd=primary)
    _git(
        "worktree", "add", "--quiet", "-b", "unmerged", str(unmerged), "origin/master", cwd=primary
    )

    _ = (dirty / "README").write_text("dirty\n", encoding="utf-8")
    _ = (unmerged / "unmerged.txt").write_text("not on master\n", encoding="utf-8")
    _git("add", "unmerged.txt", cwd=unmerged)
    _git("commit", "--quiet", "-m", "unmerged", cwd=unmerged)

    index = Path(_git("rev-parse", "--git-path", "index", cwd=merged))
    old = time.time() - 4 * 24 * 60 * 60
    os.utime(index, (old, old))
    return merged, dirty, unmerged


def test_retention_reports_only_the_clean_merged_aged_worktree_and_never_removes_one(
    *, tmp_path: Path
) -> None:
    """An aged merged worktree is reported; dirty and unmerged peers stay unmentioned.

    This is the acceptance scenario from ``Dev host disk retention``.  The
    notification threshold is zero so the one eligible fixture worktree must
    publish exactly one ntfy request without requiring a multi-gibibyte fixture.
    """
    assert _SCRIPT.is_file(), f"missing retention entry point: {_SCRIPT}"
    merged, dirty, unmerged = _linked_worktrees(tmp_path=tmp_path)
    home = tmp_path / "home"
    cache = home / ".cache" / "uv"
    cache.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ntfy_log = tmp_path / "ntfy.log"
    account = pwd.getpwuid(os.getuid())
    (bin_dir / "docker").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_dir / "uv").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_dir / "curl").write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >>"$NTFY_LOG"\n',
        encoding="utf-8",
    )
    (bin_dir / "getent").write_text(
        "#!/bin/sh\n"
        f'if test "$1" = passwd && test "$2" = "{account.pw_name}"; then\n'
        f'  printf \'%s:x:%s:%s::%s:/bin/sh\\n\' "$2" {account.pw_uid} {account.pw_gid} "$TEST_HOME"\n'
        "  exit 0\n"
        "fi\n"
        'exec /usr/bin/getent "$@"\n',
        encoding="utf-8",
    )
    for executable in bin_dir.iterdir():
        executable.chmod(0o755)

    env = os.environ | {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "NTFY_LOG": str(ntfy_log),
        "TEST_HOME": str(home),
        "LIVESPEC_DEV_HOST_RETENTION_USER": account.pw_name,
        "LIVESPEC_DEV_HOST_RETENTION_CHECKOUT_ROOTS": str(tmp_path / "no-checkouts"),
        "LIVESPEC_DEV_HOST_RETENTION_STATE_DIR": str(tmp_path / "state"),
        "LIVESPEC_DEV_HOST_TMP_ROOT": str(tmp_path / "tmp"),
        "LIVESPEC_DEV_HOST_BULK_DUMP_DIR": str(tmp_path / "bulk"),
        "LIVESPEC_DEV_HOST_WORKTREE_REPORT_DAYS": "3",
        "LIVESPEC_DEV_HOST_WORKTREE_REPORT_THRESHOLD_GIB": "0",
        "LIVESPEC_DEV_HOST_NTFY_TOPIC": "retention-test-topic",
        "LIVESPEC_DEV_HOST_NTFY_SERVER": "https://ntfy.example.invalid",
    }

    done = run_under_hang_guard(
        ["bash", str(_SCRIPT)], capture_output=True, text=True, check=False, env=env
    )

    output = done.stdout + done.stderr
    assert done.returncode == 0, output
    assert str(merged) in output, output
    assert "repo" in output and "reportable" in output and "total" in output.lower(), output
    assert str(dirty) not in output and str(unmerged) not in output, output
    assert merged.is_dir() and dirty.is_dir() and unmerged.is_dir(), output
    notifications = ntfy_log.read_text(encoding="utf-8").splitlines()
    assert len(notifications) == 1 and "retention-test-topic" in notifications[0], notifications
