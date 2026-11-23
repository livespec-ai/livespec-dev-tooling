#!/usr/bin/env bash
# dev-host-retention.sh — the dev host's standing disk retention.
#
# WHAT BROKE. Measured 2026-10-21 on the maintainer's dev host: `/` at 94% —
# 637G of 678G, 39.4G free — with no standing retention of any kind. The
# reclaimable consumers were `~/.cache/uv` at 52G, the docker store at 21G
# (7.8G of it dangling sandbox images) and `tmp/gate-runs` at 1.1G over 4935
# run directories in four governed checkouts, with no retention period defined
# anywhere. Nothing swept any of them and nothing watched the disk, so the only
# control was a human noticing. Cargo build targets are deliberately NOT swept
# here: the two large ones belong to the fabro repository's owner, whose
# retention rule governs them.
#
# THE RUN NEVER ABORTS, AND THAT IS THE POINT. A hand `uv cache prune` on
# 2026-10-21 reclaimed ~6G and then exited non-zero on one path under
# `archive-v0` it was not permitted to remove. Under a timer that is worse than
# it sounds: everything after the prune would never run, so an unattended
# retention would reclaim nothing from docker and nothing from `tmp/gate-runs`
# either. Every leg below therefore logs its own failure and returns, and the
# script does not run under `errexit`.
#
# WHY `docker image prune -f` AND NEVER `-a`. The narrow spelling removes
# DANGLING images only. `-a` additionally removes every tagged image no
# container currently uses — which on this host is the warm sandbox image store
# that the `sandbox_image_warm` role exists to keep populated, and evicting it
# re-arms the first-pull race that role closes.
#
# WHY A GATE RUN'S TERMINAL STATE IS NOT RE-DERIVED HERE. `gate-run.sh` already
# owns that predicate — its `derive_state` is documented as "the single source
# of truth for every verdict word", and RUNNING is its only non-terminal state:
# no `exit_code`, a `pid` file, and `kill -0` against it succeeding. A run that
# never published a pid is terminal, because no verdict is coming. Re-deriving
# that here would be a second implementation of a rule whose whole value is
# having one, and the failure mode of drift is removing the evidence of a gate
# that is still running. So this script asks each checkout's own installed
# runner, once per checkout, via `gate-run.sh list`.
#
# Every value below is read from the environment the systemd unit sets from the
# role's variables; the defaults are the fleet's current ones so that running
# this script by hand on the dev host does the same thing the timer does.
set -uo pipefail

RETENTION_DAYS=${LIVESPEC_DEV_HOST_RETENTION_DAYS:-7}
WORKTREE_REPORT_DAYS=${LIVESPEC_DEV_HOST_WORKTREE_REPORT_DAYS:-3}
WORKTREE_REPORT_THRESHOLD_GIB=${LIVESPEC_DEV_HOST_WORKTREE_REPORT_THRESHOLD_GIB:-40}
WORKTREE_ROOT=${LIVESPEC_DEV_HOST_WORKTREE_ROOT:-$HOME/.worktrees}
NTFY_TOPIC=${LIVESPEC_DEV_HOST_NTFY_TOPIC:-}
NTFY_SERVER=${LIVESPEC_DEV_HOST_NTFY_SERVER:-https://ntfy.sh}
CHECKOUT_ROOTS=${LIVESPEC_DEV_HOST_RETENTION_CHECKOUT_ROOTS:-/home/ubuntu/workspace}
FILESYSTEM=${LIVESPEC_DEV_HOST_RETENTION_FILESYSTEM:-/}
TMP_ROOT=${LIVESPEC_DEV_HOST_TMP_ROOT:-/tmp}
SCRATCH_RETENTION_SECONDS=${LIVESPEC_DEV_HOST_SCRATCH_RETENTION_SECONDS:-21600}
BULK_DUMP_DIR=${LIVESPEC_DEV_HOST_BULK_DUMP_DIR:-/var/tmp/livespec-dumps}
BULK_DUMP_CAP_BYTES=${LIVESPEC_DEV_HOST_BULK_DUMP_CAP_BYTES:-21474836480}
RETENTION_USER=${LIVESPEC_DEV_HOST_RETENTION_USER:-root}
UV_BIN=${LIVESPEC_DEV_HOST_RETENTION_UV_BIN:-uv}
# 900s, not 300s: on 2026-11-21 the VPS's 45G, ~200k-file cache outran 300s every
# night, the walk was cut off before it reached a root-owned .pyc, and the prune
# then aborted on it. The prune-failure repair below is what makes a cut-off
# walk safe; the budget only bounds how much of the walk completes.
UV_OWNERSHIP_BUDGET_SECONDS=${LIVESPEC_DEV_HOST_UV_OWNERSHIP_BUDGET_SECONDS:-900}
# The size cap on the uv cache, in GB (decimals allowed), enforced after the prune.
UV_CACHE_MAX_GB=${LIVESPEC_DEV_HOST_UV_CACHE_MAX_GB:-10}
UV_HEALED_UNITS=" "
RETENTION_STATE_DIR=${LIVESPEC_DEV_HOST_RETENTION_STATE_DIR:-/var/lib/livespec-dev-host-retention}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)

log() {
    printf '%s livespec-dev-host-retention: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

# `df -P` is the POSIX output format: one record per filesystem on one line,
# whatever the length of the device name, so field 4 is always the available
# blocks. Without it a long device name wraps and the reading silently becomes
# the mount point.
report_free_space() {
    local when=$1 filesystem=$2 avail
    avail=$(df -P -k "$filesystem" | awk 'NR == 2 {print $4}')
    if [[ -z $avail ]]; then
        log "WARNING: could not measure free space on $filesystem"
        return 0
    fi
    log "free space $when: $avail KiB available on $filesystem"
}

prune_docker_images() {
    local output
    if ! command -v docker >/dev/null 2>&1; then
        log "docker is not on PATH; no image prune attempted"
        return 0
    fi
    # DANGLING ONLY — see the header for why `-a` is not an option here.
    if ! output=$(docker image prune -f 2>&1); then
        log "WARNING: the docker image prune failed and the run continues: $output"
        return 0
    fi
    log "docker image prune (dangling only): ${output//$'\n'/; }"
}

# The paths a failed prune names. uv reports the path it could not remove in
# its own error output, so the paths are read back out of that rather than
# guessed: anything that looks like an absolute path in the message is logged
# on a line of its own, and the message itself is logged verbatim beside it so
# a wording change can never silently drop the evidence.
unremovable_paths() {
    printf '%s\n' "$1" | grep -oE '(/[A-Za-z0-9._@+-]+)+' | sort -u
}

# Hands every path in the uv cache that another user owns back to the cache
# owner. The walk has a time budget because a full walk of the dev host's cache
# (5.3 million entries) takes about 29 minutes, far past any budget the unit can
# spare. The budget stops the walk, so what the walk had not reached is left
# unvisited.
#
# The stamp records the START of the last walk that ran to its end or to its
# budget. Stamping only a walk that completed could never engage on the host the
# incremental design is for: every run took the full-walk branch, was cut off,
# and left no stamp. So a cut-off walk is stamped too, and the next run walks
# only what changed after that point. The cost is stated plainly: a foreign path
# older than that point that the cut-off walk never reached is no longer swept;
# a path the prune cannot remove is still named by the prune's own log. The
# start of the walk, not its end, is the stamp, so a path written while the walk
# ran is newer than the stamp and is walked next time.
restore_uv_cache_ownership() {
    local cache_dir=$1 owner_uid=$2 owner_gid=$3 stamp started ran status candidate=""
    local -a walk=(find "$cache_dir" -xdev)
    stamp="$RETENTION_STATE_DIR/uv-cache-ownership.stamp"
    if ! mkdir -p "$RETENTION_STATE_DIR"; then
        log "WARNING: could not create retention state directory $RETENTION_STATE_DIR; restoring all foreign uv-cache paths"
        stamp=
    fi
    if [[ -n $stamp ]]; then
        candidate="$stamp.candidate"
        touch "$candidate" || candidate=
        [[ ! -e $stamp ]] || walk+=(-newer "$stamp")
    fi
    walk+=(! -user "$owner_uid")
    started=$SECONDS
    timeout --kill-after=5s "$UV_OWNERSHIP_BUDGET_SECONDS" \
        "${walk[@]}" -exec chown -h "$owner_uid:$owner_gid" {} + 2>/dev/null
    status=$?
    ran=$((SECONDS - started))
    case $status in
        0)
            log "uv-cache ownership walk ran ${ran}s and completed"
            ;;
        124 | 137)
            log "WARNING: uv-cache ownership walk exceeded its ${UV_OWNERSHIP_BUDGET_SECONDS}s budget; it ran ${ran}s and was cut off before it completed; pruning continues"
            ;;
        *)
            log "WARNING: uv-cache ownership walk ran ${ran}s and ended with status $status before it completed; its stamp is not advanced; pruning continues"
            [[ -z $candidate ]] || rm -f "$candidate"
            candidate=
            ;;
    esac
    [[ -z $candidate ]] || mv -f "$candidate" "$stamp"
}

uv_cache_is_in_use() {
    local cache_dir=$1 lock_file="$1/.lock"
    [[ -e $lock_file ]] || return 1
    ! flock --exclusive --nonblock "$lock_file" true 2>/dev/null
}

# The prune runs as the retention user. When the run already executes as that
# account, uv is invoked directly; otherwise `runuser` switches to it. The
# account is compared by uid, so a login name and a numeric uid naming the same
# account take the same route, and `runuser` is handed the login name because
# it does not accept a numeric uid ("runuser: user 1000 does not exist",
# livespec-dev-tooling-spva5x).
#
# The prune is NEVER forced. `uv cache prune --force` ignores the cache lock a
# running uv or uvx process holds, and it removes any archive no cache entry
# references, including the ephemeral environment a long-running uvx process
# re-execs its interpreter from. On 2026-11-10 at 21:45:33Z a forced prune
# removed archive-v0/O0B37K2mzvi1ETZA1h2Uq under a running
# `uvx --from ansible-core ansible-playbook`, which then failed with
# "bin/python3.14: not found" (livespec-dev-tooling-7bij7b).
run_uv_cache_prune() {
    local cache_home=$1 output status retention_uid login
    local args=(cache prune)
    retention_uid=$(id -u "$RETENTION_USER" 2>/dev/null) || retention_uid=$RETENTION_USER
    if [[ $retention_uid == "$(id -u)" ]]; then
        output=$("$UV_BIN" "${args[@]}" 2>&1)
        status=$?
    else
        login=$(getent passwd "$RETENTION_USER" 2>/dev/null | cut -d: -f1)
        output=$(runuser -u "${login:-$RETENTION_USER}" -- env "HOME=$cache_home" "$UV_BIN" "${args[@]}" 2>&1)
        status=$?
    fi
    printf '%s' "$output"
    return "$status"
}

uv_lock_timeout() {
    [[ $1 == *"Timeout"* && $1 == *"waiting for lock"* ]]
}

uv_cache_prune_skipped() {
    log "uv cache prune skipped: $1; the prune is never forced, so a cache another uv process is using is left for a later run"
}

# The unit of the cache a failing path belongs to: the first two components
# below the cache root (`archive-v0/<id>`), or the first when the path is that
# shallow.
uv_cache_unit_of() {
    local cache_dir=$1 path=$2 rel first rest
    [[ $path == "$cache_dir"/* ]] || return 1
    rel=${path#"$cache_dir"/}
    first=${rel%%/*}
    rest=${rel#*/}
    if [[ $rel == */* ]]; then
        printf '%s/%s\n' "$first" "${rest%%/*}"
    else
        printf '%s\n' "$first"
    fi
}

# Recursively hands back to the cache owner every unit a failed prune named.
# Returns 0 only when it handed back a unit it had not handed back before, so
# the caller retries only when the retry can differ.
heal_foreign_paths_from_failure() {
    local cache_dir=$1 owner_uid=$2 owner_gid=$3 output=$4 path unit progressed=1
    while IFS= read -r path; do
        [[ -n $path ]] || continue
        unit=$(uv_cache_unit_of "$cache_dir" "$path") || continue
        [[ -n $unit && $unit != .. && $unit != . ]] || continue
        [[ $UV_HEALED_UNITS != *" $unit "* ]] || continue
        UV_HEALED_UNITS+="$unit "
        log "uv cache prune stopped on $path; handing $cache_dir/$unit back to $owner_uid:$owner_gid and pruning again"
        chown -R -h "$owner_uid:$owner_gid" "$cache_dir/$unit" 2>/dev/null
        progressed=0
    done < <(unremovable_paths "$output")
    return "$progressed"
}

prune_uv_cache() {
    local output path cache_home cache_dir owner_uid owner_gid
    if [[ $UV_BIN == */* && ! -x $UV_BIN ]]; then
        log "configured uv executable is not executable: $UV_BIN; no cache prune attempted"
        return 0
    fi
    if [[ $UV_BIN != */* ]] && ! command -v "$UV_BIN" >/dev/null 2>&1; then
        log "configured uv executable is not on PATH: $UV_BIN; no cache prune attempted"
        return 0
    fi
    cache_home=$(getent passwd "$RETENTION_USER" 2>/dev/null | cut -d: -f6)
    cache_dir=${LIVESPEC_DEV_HOST_UV_CACHE_DIR:-${cache_home:+$cache_home/.cache/uv}}
    if [[ -n $cache_dir && -d $cache_dir ]]; then
        owner_uid=$(id -u "$RETENTION_USER" 2>/dev/null) || owner_uid=
        owner_gid=$(id -g "$RETENTION_USER" 2>/dev/null) || owner_gid=
        if [[ -n $owner_uid && -n $owner_gid ]]; then
            restore_uv_cache_ownership "$cache_dir" "$owner_uid" "$owner_gid"
        fi
        if uv_cache_is_in_use "$cache_dir"; then
            uv_cache_prune_skipped "the uv cache $cache_dir is in use by another uv process"
            return 0
        fi
    fi
    local status round=0
    while :; do
        output=$(run_uv_cache_prune "$cache_home")
        status=$?
        if [[ $status -eq 0 ]]; then
            log "uv cache prune: ${output//$'\n'/; }"
            return 0
        fi
        if uv_lock_timeout "$output"; then
            uv_cache_prune_skipped "uv timed out waiting for the cache lock another uv process holds"
            return 0
        fi
        # The prune stopped on a path the retention user cannot remove: a
        # foreign-owned path the (budgeted) ownership walk had not reached.
        # Hand that path's whole archive back to the cache owner and prune
        # again, never forced. A unit already handed back is not tried twice,
        # so a failure ownership does not explain ends the loop.
        round=$((round + 1))
        if [[ $round -gt 25 || -z ${owner_uid:-} || -z ${owner_gid:-} ]]; then
            break
        fi
        if ! heal_foreign_paths_from_failure "$cache_dir" "$owner_uid" "$owner_gid" "$output"; then
            break
        fi
    done
    log "WARNING: the uv cache prune did not complete: ${output//$'\n'/; }"
    while IFS= read -r path; do
        [[ -n $path ]] || continue
        log "uv cache prune could not remove $path; continuing with the remaining steps"
    done < <(unremovable_paths "$output")
}

resolve_uv_cache_dir() {
    local cache_home
    cache_home=$(getent passwd "$RETENTION_USER" 2>/dev/null | cut -d: -f6)
    printf '%s\n' "${LIVESPEC_DEV_HOST_UV_CACHE_DIR:-${cache_home:+$cache_home/.cache/uv}}"
}

# Bounds the uv cache by UV_CACHE_MAX_GB. The prune only removes what uv deems
# unreferenced, so a cache can still sit far over any budget (45G measured on
# 2026-11-21). A cache under the cap is left in place. A cache over it is
# emptied (everything but the lock file) as root, and only when no uv process
# holds it: the same flock the prune respects. uv rebuilds what it needs.
enforce_uv_cache_cap() {
    local cache_dir cap_kib before_kib after_kib
    cache_dir=$(resolve_uv_cache_dir)
    if [[ -z $cache_dir || $cache_dir == / || ! -d $cache_dir ]]; then
        return 0
    fi
    cap_kib=$(awk -v g="$UV_CACHE_MAX_GB" 'BEGIN { printf "%d", g * 1048576 }' 2>/dev/null)
    if [[ -z $cap_kib || $cap_kib -le 0 ]]; then
        log "uv cache size cap is not set ($UV_CACHE_MAX_GB GB); no cap enforced"
        return 0
    fi
    before_kib=$(du -sk -x "$cache_dir" 2>/dev/null | awk '{print $1}')
    if [[ -z $before_kib ]]; then
        log "WARNING: could not measure the uv cache $cache_dir; no cap enforced"
        return 0
    fi
    if [[ $before_kib -le $cap_kib ]]; then
        log "uv cache $cache_dir is ${before_kib} KiB, at or under its ${UV_CACHE_MAX_GB} GB cap; left in place"
        return 0
    fi
    if uv_cache_is_in_use "$cache_dir"; then
        log "uv cache $cache_dir is ${before_kib} KiB, over its ${UV_CACHE_MAX_GB} GB cap, but is in use by another uv process; left for a later run"
        return 0
    fi
    log "uv cache $cache_dir is ${before_kib} KiB, over its ${UV_CACHE_MAX_GB} GB cap; removing its contents"
    if ! find "$cache_dir" -mindepth 1 -maxdepth 1 ! -name .lock -exec rm -rf -- {} + 2>/dev/null; then
        log "WARNING: some uv cache paths could not be removed"
    fi
    after_kib=$(du -sk -x "$cache_dir" 2>/dev/null | awk '{print $1}')
    log "uv cache cap enforced: ${before_kib} KiB before, ${after_kib:-unknown} KiB after, cap ${UV_CACHE_MAX_GB} GB"
}

# The scratch and bulk legs are separate because their liveness and ordering
# rules are independent from the checkout-owned gate-run predicate above.
# Keeping them in a sibling also keeps this orchestration script cohesive.
if [[ -r $SCRIPT_DIR/dev-host-retention-scratch.sh ]]; then
    # shellcheck source=dev-host-retention-scratch.sh
    source "$SCRIPT_DIR/dev-host-retention-scratch.sh"
else
    log "WARNING: scratch retention helper is not installed; tmpfs cleanup is skipped"
fi

# Seconds since the epoch for a gate run's `started_at`, or nothing when the
# record cannot be read. "Older than the retention period" is anchored on
# `started_at` because it is the ONE timestamp every run directory carries: the
# gate writes it before the gate starts, so even a run that died before
# publishing a pid has one.
started_epoch() {
    local started
    started=$(cat "$1/started_at" 2>/dev/null) || return 0
    [[ -n $started ]] || return 0
    date -u -d "$started" +%s 2>/dev/null
}

remove_aged_gate_runs() {
    local checkout=$1 cutoff=$2
    local store="$checkout/tmp/gate-runs"
    [[ -d $store ]] || return 0
    local runner="$checkout/dev-tooling/gate-run.sh"
    if [[ ! -f $runner ]]; then
        log "SKIP $store: the checkout carries no dev-tooling/gate-run.sh, so the" \
            "terminal-state predicate this retention reuses is not available"
        return 0
    fi
    local listing
    if ! listing=$(cd "$checkout" && bash "$runner" list 2>&1); then
        log "SKIP $store: gate-run.sh list failed: ${listing//$'\n'/; }"
        return 0
    fi
    local run_id state dir epoch removed=0 kept=0
    while read -r run_id state _; do
        dir="$store/$run_id"
        [[ -n $run_id && -d $dir ]] || continue
        # RUNNING is gate-run.sh's only non-terminal state: the recorded process
        # is alive, so this run's evidence is still being written.
        if [[ $state == RUNNING ]]; then
            kept=$((kept + 1))
            continue
        fi
        epoch=$(started_epoch "$dir")
        if [[ -z $epoch ]]; then
            log "KEEP $dir: no readable started_at, so its age cannot be established"
            kept=$((kept + 1))
            continue
        fi
        if ((epoch > cutoff)); then
            kept=$((kept + 1))
            continue
        fi
        if rm -rf -- "$dir"; then
            log "removed gate run $dir (state $state, older than ${RETENTION_DAYS}d)"
            removed=$((removed + 1))
        else
            log "WARNING: could not remove gate run $dir"
            kept=$((kept + 1))
        fi
    done <<<"$listing"
    log "$store: removed $removed gate runs, kept $kept"
}

sweep_checkout_roots() {
    local cutoff candidate root
    cutoff=$(( $(date -u +%s) - RETENTION_DAYS * 86400 ))
    local roots
    read -r -a roots <<<"$CHECKOUT_ROOTS"
    for root in "${roots[@]}"; do
        if [[ ! -d $root ]]; then
            log "no such checkout root: $root"
            continue
        fi
        for candidate in "$root"/*/; do
            [[ -d "${candidate}.git" ]] || continue
            remove_aged_gate_runs "${candidate%/}" "$cutoff"
        done
    done
}

# The report only makes claims that can be checked without updating a worktree.
# The local remote-tracking ref must exactly match the remote's advertised HEAD
# branch, so a stale tracking ref cannot make a worktree look merged. `git
# cherry` then accepts either ancestry or a sequence of patch-equivalent
# commits, which is the safe case after a squash or rebased merge.
worktree_default_ref() {
    local worktree=$1 remote=$2 symref branch local_ref local_oid remote_oid
    symref=$(git -C "$worktree" ls-remote --symref "$remote" HEAD 2>/dev/null \
        | awk '$1 == "ref:" && $2 ~ /^refs\/heads\// && $3 == "HEAD" { print $2; exit }')
    [[ -n $symref ]] || return 1
    branch=${symref#refs/heads/}
    local_ref="refs/remotes/$remote/$branch"
    local_oid=$(git -C "$worktree" rev-parse --verify "${local_ref}^{commit}" 2>/dev/null) || return 1
    remote_oid=$(git -C "$worktree" ls-remote "$remote" "$symref" 2>/dev/null | awk 'NR == 1 { print $1 }')
    [[ -n $remote_oid && $local_oid == "$remote_oid" ]] || return 1
    printf '%s\n' "$local_ref"
}

report_merged_aged_worktrees() {
    local cutoff dotgit worktree status index_mtime remote default_ref cherry branch repository size_kib
    local total_kib=0 count=0
    cutoff=$(( $(date -u +%s) - WORKTREE_REPORT_DAYS * 86400 ))
    [[ -d $WORKTREE_ROOT ]] || {
        log "worktree retention total: 0 KiB across 0 worktree(s)"
        return 0
    }
    while IFS= read -r -d '' dotgit; do
        worktree=${dotgit%/.git}
        index_mtime=$(stat -c %Y "$(git -C "$worktree" rev-parse --git-path index 2>/dev/null)" 2>/dev/null) || continue
        [[ $index_mtime =~ ^[0-9]+$ && $index_mtime -le $cutoff ]] || continue
        # `git status` can refresh a clean index, so the age must be captured
        # first: it is the index age at the start of this report that matters.
        status=$(git -C "$worktree" status --porcelain --untracked-files=all 2>/dev/null) || continue
        [[ -z $status ]] || continue
        remote=origin
        git -C "$worktree" remote get-url "$remote" >/dev/null 2>&1 || continue
        default_ref=$(worktree_default_ref "$worktree" "$remote") || continue
        cherry=$(git -C "$worktree" cherry "$default_ref" HEAD 2>/dev/null) || continue
        grep -q '^+' <<<"$cherry" && continue
        branch=$(git -C "$worktree" symbolic-ref --quiet --short HEAD 2>/dev/null || printf detached)
        repository=$(git -C "$worktree" remote get-url "$remote" 2>/dev/null || printf unknown)
        size_kib=$(du -sk -x -- "$worktree" 2>/dev/null | awk 'NR == 1 { print $1 }')
        [[ $size_kib =~ ^[0-9]+$ ]] || continue
        log "worktree retention: path=$worktree repository=$repository branch=$branch size=${size_kib} KiB"
        total_kib=$((total_kib + size_kib))
        count=$((count + 1))
    done < <(find "$WORKTREE_ROOT" -type f -name .git -print0 2>/dev/null)
    log "worktree retention total: ${total_kib} KiB across ${count} worktree(s)"
    if [[ ! $WORKTREE_REPORT_THRESHOLD_GIB =~ ^[0-9]+$ ]]; then
        log "WARNING: invalid worktree report threshold '$WORKTREE_REPORT_THRESHOLD_GIB'; no notification sent"
        return 0
    fi
    if ((total_kib < WORKTREE_REPORT_THRESHOLD_GIB * 1024 * 1024)); then
        return 0
    fi
    if [[ -z $NTFY_TOPIC ]]; then
        log "WARNING: no ntfy topic configured; worktree report notification not sent"
        return 0
    fi
    if curl --fail --silent --show-error -H 'Title: Dev host worktree retention report' \
        -d "${count} merged, clean, aged worktree(s) total ${total_kib} KiB" \
        "$NTFY_SERVER/$NTFY_TOPIC"; then
        log "sent worktree retention notification for ${count} worktree(s), ${total_kib} KiB"
    else
        log "WARNING: ntfy publication failed for worktree retention report"
    fi
}

log "gate-run retention period: ${RETENTION_DAYS} days; scratch retention: ${SCRATCH_RETENTION_SECONDS}s"
report_free_space before "$FILESYSTEM"
report_free_space before /tmp
prune_docker_images
prune_uv_cache
enforce_uv_cache_cap
sweep_checkout_roots
report_merged_aged_worktrees
if declare -F reclaim_scratch_and_bulk >/dev/null; then
    reclaim_scratch_and_bulk "$TMP_ROOT" "$SCRATCH_RETENTION_SECONDS" "$BULK_DUMP_DIR" "$BULK_DUMP_CAP_BYTES"
fi
report_free_space after "$FILESYSTEM"
report_free_space after /tmp
