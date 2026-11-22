# Host-guard escape backfills

Each audited HOST-GUARD-ESCAPE use is recorded on a ledger item before the
commands run (`HOST-GUARD-ESCAPE: command=... reason=... backfill-due=...`)
and answered by a committed backfill: this file, in the pull request that
fixes the cause, plus a `HOST-GUARD-BACKFILL: pr=<repo>#<n>` comment on the
same item (read by `scripts/coordinator/host-guard-backfills`).

## 2026-11-22: VPS root filesystem full (livespec-dev-tooling-tr5jkd)

- Escape recorded on: `livespec-dev-tooling-6tgd2z`.
- Host: the VPS (vmi3006760). Incident: `/dev/sda1` reached 100 percent
  (3.3M free of 678G); the shared Dolt died at 11:16:43Z with "no space left on
  device" and every ledger read and write across the fleet failed until space
  was freed (Dolt up again 11:18:03Z).
- Cause fixed by the pull request carrying this record: the daily uv-cache
  prune never completed (ownership walk over its 300 s budget, then a
  permission error on a root-owned `.pyc`), the cache grew to 45G, and the
  capacity alert was push-only with no owner or runbook.

Commands run by hand on the VPS under the escape:

1. `journalctl --vacuum-size=500M`
2. `uv cache prune` and `uv cache clean`, plus `sudo rm -rf` of the root-owned
   archive fragments under `~/.cache/uv`.
3. `rm -rf` of five aged directories under `/var/tmp/livespec-dumps`:
   `scratch-archive-838dde37`, `ksb`, `tmp-reap-20261112`,
   `livespec-overseer-exercise.7RmSUf`, `cglwxw`.
4. A tar-stream copy of `/data/dolt-incident-backup-20261101T2010Z` to
   hetzner-xubuntu (verified by a matching 426-file sha256 manifest), then
   removal of the VPS copy.
5. `git worktree remove --force` of 35 merged, detached worktrees under
   `~/.worktrees`.

The same escape id was also used for read-only scripts piped through ssh.

Measured but not touched (owners listed on the work item):
`/var/lib/doltdb/backup-verification` 44G, `/srv/arq-vps-root-snapshot` 205G,
`~/.worktrees` 80G in 559 directories, `~/.claude/projects` 23G.
