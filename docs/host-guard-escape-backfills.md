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

## 2026-11-22: incident-merge 5157 start and retention read-back run (livespec-dev-tooling-bqnzcm, -tr5jkd)

- Escape recorded on: `livespec-dev-tooling-6tgd2z` (three comments, 2026-11-22).
- Host: the VPS (vmi3006760).
- Why no committed route: both are one-shot starts of a oneshot systemd unit
  the committed `incident_observer` and `dev_host_retention` roles install but
  deliberately never run; the apply installs the unit, it does not execute it.

Commands run by hand on the VPS under the escape:

1. `systemctl reset-failed livespec-incident-merge@5157.service`, then
   `systemctl start livespec-incident-merge@5157.service`: the fresh merge of
   expedited repair pull request 5157, authorized by legacy-coordinator-agent
   (coordinator decision R301/R493) after the App Contents: write grant was
   read back. Result: exit 0, `incident-merge-runner-merged: pr 5157 master
   d0cf7db823f3761bc0080dc797c848daef83dee8`, no `incident-merge-app-token-refused`.
2. `systemctl start livespec-dev-host-retention.service`: the first run after
   the `dev_host_retention` apply from livespec-dev-tooling#5279, read back to
   confirm the uv prune and cap. Result: exit 0, uv cache pruned to 137,632 KiB.
3. One `POST http://127.0.0.1:8765/bind` to the livespec-dev-tooling observer,
   with the control bearer read on the host and never printed, and exactly the
   three keys `repository`, `head_sha` (`d0cf7db823f3761bc0080dc797c848daef83dee8`)
   and `run_id` (45053854447, the green master `ci.yml` push run): the gtx5nl
   attempt-1 arm bind, ordered by coordinator ruling R301. Result: HTTP 202,
   `admitted`, "retained arm bound to its authenticated master run". It is an
   authenticated control-plane call with no committed apply route.
