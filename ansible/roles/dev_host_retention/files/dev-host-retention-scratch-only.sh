#!/usr/bin/env bash
# Frequent retention for tmpfs scratch only.  The daily entry point owns every
# slower leg; this one deliberately shares only the liveness-aware scratch and
# pytest cleanup helper.
set -uo pipefail

TMP_ROOT=${LIVESPEC_DEV_HOST_TMP_ROOT:-/tmp}
SCRATCH_RETENTION_SECONDS=${LIVESPEC_DEV_HOST_SCRATCH_RETENTION_SECONDS:-21600}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
SCRATCH_HELPER=${LIVESPEC_DEV_HOST_RETENTION_SCRATCH_HELPER:-$SCRIPT_DIR/dev-host-retention-scratch.sh}

log() {
    printf '%s livespec-dev-host-retention: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

report_tmp_free_space() {
    local when=$1 avail
    avail=$(df -P -k /tmp | awk 'NR == 2 {print $4}')
    if [[ -z $avail ]]; then
        log "WARNING: could not measure free space on /tmp"
        return 0
    fi
    log "free space $when: $avail KiB available on /tmp"
}

if [[ -r $SCRATCH_HELPER ]]; then
    # shellcheck source=dev-host-retention-scratch.sh
    source "$SCRATCH_HELPER"
else
    log "WARNING: scratch retention helper is not installed; tmpfs cleanup is skipped"
fi

log "scratch-only retention period: ${SCRATCH_RETENTION_SECONDS}s"
report_tmp_free_space before
if declare -F remove_old_scratch >/dev/null; then
    remove_old_scratch "$TMP_ROOT" "$SCRATCH_RETENTION_SECONDS"
fi
report_tmp_free_space after
