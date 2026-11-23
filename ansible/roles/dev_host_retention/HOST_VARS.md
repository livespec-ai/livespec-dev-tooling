# `dev_host_retention` — per-host values for the inventory's `host_vars`

The dev host's standing disk retention: a root-run daily oneshot that removes
dangling docker images, restores the retention user's uv-cache ownership before
pruning as that user, and reclaims aged gate-run, Claude Code and pytest
scratch. A separate scratch-only timer runs the Claude Code and pytest legs
every two hours; it uses the same liveness scan and fails closed, but never
touches docker, the uv cache, gate runs, marketplace backups or bulk dumps. A
third timer checks root and `/tmp` every 15 minutes and alerts the host's
`claude_ntfy_topic` before either fills.

**Why it exists.** Measured 2026-10-21 for coordinator R510: `/` at 94% — 637G
of 678G, 39.4G free — with no standing retention of any kind. The reclaimable
consumers were `~/.cache/uv` at 52G, the docker store at 21G (7.8G of it
dangling sandbox images), and `tmp/gate-runs` at 1.1G over 4935 run directories
in four governed checkouts, with no retention period defined anywhere. The only
control was a human noticing (work-item `livespec-dev-tooling-fj6dm5`).

**What one run reclaims, and what it leaves.** Governed by
`SPECIFICATION/non-functional-requirements.md` §"Dev host disk retention":

- dangling docker images go; every tagged image and every image a container
  uses stays;
- root restores every path in the retention user's uv cache to that user's
  ownership, then the retention user prunes it; a path the prune cannot remove
  is LOGGED and the run continues — it never aborts;
- a gate run under a governed checkout's `tmp/gate-runs` is removed only when
  it is TERMINAL and older than the retention period; a run whose recorded
  process is alive stays, whatever its age;
- linked worktrees below the retention user's `~/.worktrees` are only
  **reported**, never removed, when they are clean, their index is older than
  the report period, and their content is on the remote default branch; the
  report includes their total and notifies `claude_ntfy_topic` when it reaches
  the configured threshold;
- old `/tmp/claude-<uid>/<project>/<session-id>` directories go only when no
  process carries their session id in `CLAUDE_CODE_SESSION_ID`; old pytest base
  temp entries go; a live session always stays;
- bulk dumps are capped oldest-first, but only under a root-filesystem
  directory: the role refuses a tmpfs location;
- each run logs what it removed and the free space of `/` and `/tmp` before and
  after.

**Multi-GB artifacts go to `/var/tmp/livespec-dumps`, never `/tmp`.** This
covers a `docker export` tar, an extracted image tree, a copied home directory,
or a journal copy. `/tmp` is a 48G tmpfs shared by every seat's Bash capture,
heredocs, gates and factory preflights, and a full `/tmp` breaks all of them.
The bulk-dump directory is on `/`. Each run caps it at
`dev_host_retention_bulk_dump_cap_bytes` (20G) by removing the oldest files
first, so put only artifacts you can afford to lose there.
- The role does not create the directory. Run
  `mkdir -p /var/tmp/livespec-dumps` before the first write; `/var/tmp` is
  world-writable with the sticky bit.
- Why this rule exists: a session scratchpad under `/tmp/claude-<uid>/` is
  removed only after its session has ended, so a LIVE seat's bulk files stay
  there until that seat removes them. Measured 2026-11-10: three live seats
  added 7.1G to `/tmp` in 25 minutes. The largest share was a 3.2G
  `docker export` tar plus its 0.6G extract, and `/tmp` rose from 62% to 77%.

**Cargo build targets are deliberately out of scope.** The two large ones
measured on 2026-10-21 (`/data/projects/fabro/target` at 129G and the shared
`~/.worktrees/fabro/factory-wave-c/target` at 122G) belong to the fabro
repository's owner, whose retention rule governs them. A sweep here would
delete a live shared `CARGO_TARGET_DIR` out from under a running build.

**Why the terminal-state predicate is borrowed and not re-derived.**
`gate-run.sh`'s `derive_state` is documented as "the single source of truth for
every verdict word", and `RUNNING` is its only non-terminal state: no
`exit_code`, a `pid` file, and `kill -0` against it succeeding. A run that
never published a pid is terminal, because no verdict is coming. So the script
asks each checkout's own installed `dev-tooling/gate-run.sh list` once per
checkout rather than carrying a second copy of that rule, whose drift would
show up as deleting the evidence of a gate that is still running. A checkout
with no installed runner is SKIPPED and says so.

## The variables

| variable | default | what it is |
| --- | --- | --- |
| `dev_host_retention_gate_run_days` | `7` | **THE GATE-RUN RETENTION PERIOD**, in whole days: how long a terminal gate run's evidence survives, anchored on the run's own `started_at` |
| `dev_host_retention_worktree_report_days` | `3` | whole days since a linked worktree's index was last written before a clean, merged worktree beneath `~/.worktrees` is named in the report; reporting never removes it |
| `dev_host_retention_worktree_report_threshold_gib` | `40` | total size in GiB at or above which the worktree report sends one ntfy notification to `claude_ntfy_topic` |
| `dev_host_retention_scratch_retention_hours` | `6` | how long Claude Code and pytest scratch must be untouched before removal |
| `dev_host_retention_scratch_on_unit_active_sec` | `2h` | cadence of the scratch-only Claude Code and pytest retention timer |
| `dev_host_retention_root_threshold_percent` | `85` | root-filesystem used-share alert threshold |
| `dev_host_retention_tmp_threshold_percent` | `75` | `/tmp` used-share alert threshold |
| `dev_host_retention_bulk_dump_dir` | `/var/tmp/livespec-dumps` | dump directory, required to resolve onto the root filesystem and never tmpfs |
| `dev_host_retention_bulk_dump_cap_bytes` | `21474836480` | 20 G (20 GiB) bulk-dump cap; the oldest files go first |
| `dev_host_retention_retired_hourly_crons` | `[/etc/cron.hourly/fstrim, /etc/cron.hourly/free]` | the hand-installed hourly crons the role keeps ABSENT; see "Retired hourly crons" below |
| `dev_host_retention_fstrim_timer` | `fstrim.timer` | the weekly systemd trim timer the role keeps enabled and started |
| `dev_host_retention_uv_cache_max_gb` | `10` | size cap on the uv cache in GB, enforced after the prune: a cache over it that no uv process holds is emptied, a cache under it is left in place |
| `dev_host_retention_alert_owner` | `vps-control-node-ops seat (escalate to legacy-coordinator-agent)` | named in every capacity alert |
| `dev_host_retention_alert_runbook` | this file, "Disk full: first steps" | named in every capacity alert |
| `dev_host_retention_alert_ledger_epic` | `livespec-dev-tooling-6tgd2z` | the coordinator epic each alert is also commented on, so a seat reads it within a tick; empty disables the ledger record |
| `dev_host_retention_alert_ledger_dir` | `/home/ubuntu/workspace/livespec-dev-tooling` | the ledger checkout the root unit runs `bd` from |
| `dev_host_retention_alert_ledger_wrapper` | `/usr/local/bin/with-livespec-env.sh` | the credential wrapper; if it or the checkout is unreachable the check logs a WARNING and alerts by ntfy only |
| `dev_host_retention_capacity_repeat_interval_seconds` | `3600` | one-hour minimum interval between repeated capacity notifications per filesystem |
| `dev_host_retention_user` | `root` | the login the retention runs as; see below, it is the one value the dev host must set |
| `dev_host_retention_uv_bin` | `/usr/bin/uv` | absolute path to the uv executable the retention invokes while pruning that user's cache |
| `dev_host_retention_uv_installs_dir` | `/home/<user>/.local/share/mise/installs/uv` | read only to list the installed mise uv versions when the converge refuses a missing `dev_host_retention_uv_bin` |
| `dev_host_retention_checkout_roots` | `[/home/ubuntu/workspace]` | the directories the governed checkouts sit directly inside; the sweep descends one level and takes every entry carrying a `.git` |
| `dev_host_retention_filesystem` | `/` | the filesystem whose free space each run reports before and after |
| `dev_host_retention_bin` | `/usr/local/sbin/livespec-dev-host-retention` | where the retention script is installed |
| `dev_host_retention_unit_dir` | `/etc/systemd/system` | where the retention units are installed |
| `dev_host_retention_service` | `livespec-dev-host-retention.service` | the oneshot unit the timer triggers |
| `dev_host_retention_timer` | `livespec-dev-host-retention.timer` | the timer the converge enables and starts |
| `dev_host_retention_scratch_bin` | `/usr/local/sbin/livespec-dev-host-retention-scratch` | scratch-and-pytest-only retention entry point |
| `dev_host_retention_scratch_service` | `livespec-dev-host-retention-scratch.service` | oneshot unit for the scratch-only timer |
| `dev_host_retention_scratch_timer` | `livespec-dev-host-retention-scratch.timer` | every-two-hours scratch-only timer |
| `dev_host_retention_timer_enabled` | `true` | **THE COMMITTED HOLD**: `false` stops and disables both retention timers on every converge; see "Holding the timer" below |
| `dev_host_retention_on_calendar` | `daily` | the cadence; the ratified section states a daily floor |
| `dev_host_retention_randomized_delay_sec` | `30m` | jitter, so the reclaim does not land in the same second as every other daily unit |
| `dev_host_retention_timeout_start_sec` | `30min` | bounds ONE run; the first run after this role lands walks the whole gate-run backlog |

**Why `dev_host_retention_user` is the one value a host must set.** It is the
cache owner: root restores this user's ownership below `~/.cache/uv`, then runs
`uv cache prune` as this user. A root prune would leave the measured user's
cache behind. The default is `root` because it is the only value that is right
for a host nobody has set this on.

**Why `dev_host_retention_uv_bin` is an absolute path.** The systemd unit runs
as root, whose PATH does not include a login's mise shims. The unit passes this
configured executable to the script, which sets the retention user's HOME when
it invokes a non-root user's uv. Point it at a concrete, version-pinned binary,
never a mise shim: run from the unit, with cwd `/` and no project configuration,
the shim fails with `No version is set for shim: uv`, so the prune never runs
(measured on the dev host 2026-11-02).

The converge FAILS when the configured path is missing or not executable, and
the failure names the installed mise uv versions. A version-pinned install is
removed by an uninstall, and the script on its own would only log that and
carry on, which on an unattended timer nobody reads.

Linked worktrees need no entry of their own: a worktree's gate runs are written
to its PRIMARY checkout's store, which is why a run outlives the worktree that
started it.

```yaml
# vps — the maintainer's dev host, where the checkouts and the uv cache are the
# `ubuntu` login's (the same login `codex_config_user` and `fabro_server_host_user`
# name).
dev_host_retention_user: ubuntu
dev_host_retention_uv_bin: /home/ubuntu/.local/share/mise/installs/uv/0.11.10/uv-x86_64-unknown-linux-musl/uv
```

## Operator procedure

The converge is the whole procedure, and it restarts nothing on the host:

```bash
just ansible-drift ansible/dev-host.yml --tags dev_host_retention
just ansible-apply ansible/dev-host.yml --tags dev_host_retention
```

To read what the retention has reclaimed, and when it next fires:

```bash
systemctl list-timers livespec-dev-host-retention.timer livespec-dev-host-retention-scratch.timer livespec-dev-host-capacity-check.timer
journalctl -u livespec-dev-host-retention.service --since -2d
journalctl -u livespec-dev-host-retention-scratch.service --since -2d
```

Silence is not success: one run logs its retention period, the free space
before and after, one line per leg, and one summary line per governed checkout.
A run that reports `removed 0 gate runs` on every checkout and no change in
free space has nothing left to reclaim; a run that logs `uv cache prune could
not remove <path>` has reclaimed everything else and named what it could not.

To run one retention by hand — the same thing the timer does:

```bash
sudo -u ubuntu /usr/local/sbin/livespec-dev-host-retention
```

## Holding the timer

To stop either retention from firing, for example while a defect in it is fixed,
set `dev_host_retention_timer_enabled: false` in the host's `host_vars` and
converge. Both timers are stopped and disabled, and every later converge keeps
them so. A hand `systemctl stop` is not a hold: the next converge of this role
restarts the timers, and because they are `Persistent=true` they then fire any
missed run at once. Release the hold by setting the variable back to `true` and
converging. Expect the missed runs to fire right away.

The uv cache prune is never forced. When another uv process holds the cache
lock, the run logs `uv cache prune skipped: …` and leaves the cache for a later
run, because `uv cache prune --force` removes the ephemeral environment a
running `uvx` re-execs its interpreter from (livespec-dev-tooling-7bij7b).

## Retired hourly crons

`/` is trimmed two ways, and the role keeps it that way: the root filesystem's
online `discard` mount option trims blocks as they are freed, and systemd's
weekly `fstrim.timer` sweeps whatever that misses. The role REMOVES
`/etc/cron.hourly/fstrim`, a `fstrim /` every hour that was hand-installed on
2026-01-06 and owned by no package. Measured 2026-11-02, one hourly run took
10 min 57 s in uninterruptible IO wait and discarded about 85 GiB, raising IO
pressure from :17 to :45 past every hour (2.4-3.2 TiB of discards a day), all
of it free space online discard had already trimmed. The maintainer approved
its removal.


```bash
sudo systemctl disable --now livespec-dev-host-retention.timer
sudo rm -f /etc/systemd/system/livespec-dev-host-retention.{service,timer} \
           /usr/local/sbin/livespec-dev-host-retention
sudo systemctl daemon-reload
```

Nothing else on the host changes: the retention holds no state of its own.

## Expiry

This control is retired when the consumers it sweeps stop accumulating without
bound — when `gate-run.sh` reaps its own store, and when the sandbox image
lifecycle leaves no dangling layers behind. Until then the dev host has no
other standing reclamation: the `disk_guard` role is `hp-xubuntu`'s low-water
backstop and is not included by `ansible/dev-host.yml`.

## Disk full: first steps

Read this when a "Dev host capacity alert" arrives (ntfy, or the comment on
`livespec-dev-tooling-6tgd2z`). The VPS filled on 2026-11-22 after 65 alerts that
nobody owned; the owner named in the alert acts on it within one coordinator
tick. Measure first (`df -P /`, `du -xsh <path>`), then reclaim, largest first:

1. **uv cache** (`~/.cache/uv`, 45G on the VPS). The daily retention prunes it
   and caps it at `dev_host_retention_uv_cache_max_gb`. To act now:
   `systemctl start livespec-dev-host-retention.service` and read its journal.
   A hand `uv cache prune` aborts on root-owned paths; the unit hands them back
   to the cache owner and retries. Never `--force`: a running `uvx` loses its
   environment.
2. **`~/.worktrees`** (80G in 559 directories on the VPS). Remove merged,
   detached worktrees with `git worktree remove` (never `rm -rf` a worktree
   with unmerged work).
3. **`/var/tmp/livespec-dumps`**: the bulk-dump leg caps it at
   `dev_host_retention_bulk_dump_cap_bytes`; aged directories beyond that are
   safe to remove.
4. **Journal**: `journalctl --disk-usage`, then `journalctl --vacuum-size=500M`.
5. Other measured consumers on the VPS: `/var/lib/doltdb/backup-verification`
   (failed `dolt-backup-oversized-verify`), `/srv/arq-vps-root-snapshot`
   (failed `arq-vps-root-snapshot.service`), `~/.claude/projects`. These belong
   to their owners; file or comment rather than delete.

**The escape procedure.** On a fleet host the host guard refuses these
commands from a seat. When the disk is at or near 100 percent and the ledger is
failing, use the audited HOST-GUARD-ESCAPE: record the escape id and the exact
commands on `livespec-dev-tooling-6tgd2z` before running them, and backfill a
committed record afterwards (see `docs/host-guard-escape-backfills.md`).
Prefer the committed route above; the escape is for a host that is already
down.
