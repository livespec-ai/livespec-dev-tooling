#!/usr/bin/env bash
# Alert once per repeat interval when root or tmpfs capacity crosses its limit.
set -uo pipefail

ROOT_THRESHOLD=${LIVESPEC_DEV_HOST_ROOT_THRESHOLD_PERCENT:-85}
TMP_THRESHOLD=${LIVESPEC_DEV_HOST_TMP_THRESHOLD_PERCENT:-75}
REPEAT_SECONDS=${LIVESPEC_DEV_HOST_CAPACITY_REPEAT_SECONDS:-3600}
STATE_DIR=${LIVESPEC_DEV_HOST_CAPACITY_STATE_DIR:-/var/lib/livespec-dev-host-capacity}
TOPIC=${LIVESPEC_DEV_HOST_NTFY_TOPIC:-}
SERVER=${LIVESPEC_DEV_HOST_NTFY_SERVER:-https://ntfy.sh}
NTFY_TOKEN_FILE=${LIVESPEC_DEV_HOST_NTFY_TOKEN_FILE:-}
# Who acts on the alert and where the first steps are written. A push nobody
# owns is a push nobody reads (the VPS filled on 2026-11-22 after 65 alerts).
OWNER=${LIVESPEC_DEV_HOST_ALERT_OWNER:-unassigned}
RUNBOOK=${LIVESPEC_DEV_HOST_ALERT_RUNBOOK:-ansible/roles/dev_host_retention/HOST_VARS.md}
# Where a seat reads it: a comment on the coordinator epic, written through the
# credential wrapper from the ledger checkout. Empty LEDGER_EPIC disables it.
LEDGER_EPIC=${LIVESPEC_DEV_HOST_ALERT_LEDGER_EPIC:-}
LEDGER_DIR=${LIVESPEC_DEV_HOST_ALERT_LEDGER_DIR:-}
LEDGER_WRAPPER=${LIVESPEC_DEV_HOST_ALERT_LEDGER_WRAPPER:-/usr/local/bin/with-livespec-env.sh}

log() { printf '%s livespec-dev-host-capacity: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

# Keep the token out of the unit and our own output.  The optional token file
# is deliberately read at runtime so secret projection can rotate it without
# putting its contents in Ansible inventory or a systemd environment value.
ntfy_auth_args=()
configure_ntfy_auth() {
    local token=
    if [[ -n $NTFY_TOKEN_FILE && -r $NTFY_TOKEN_FILE && -s $NTFY_TOKEN_FILE ]]; then
        token=$(<"$NTFY_TOKEN_FILE")
    fi
    if [[ -n $token ]]; then
        ntfy_auth_args=(-H "Authorization: Bearer $token")
    else
        log "publishing ntfy alerts anonymously"
    fi
}

filesystem_values() {
    df -P -k "$1" | awk 'NR == 2 {gsub(/%/, "", $5); print $5, $4}'
}

may_notify() {
    local marker=$1 now last=0
    now=$(date -u +%s)
    [[ -f $marker ]] && last=$(cat "$marker" 2>/dev/null || printf 0)
    ((now - last >= REPEAT_SECONDS))
}

# Records the alert where a seat reads it. Degrades to the push alone, with a
# WARNING, when the wrapper, the checkout or the credential is unreachable.
record_in_ledger() {
    local text=$1 output
    [[ -n $LEDGER_EPIC ]] || return 0
    if [[ ! -x $LEDGER_WRAPPER || -z $LEDGER_DIR || ! -d $LEDGER_DIR ]]; then
        log "WARNING: ledger record unavailable (wrapper $LEDGER_WRAPPER, checkout '$LEDGER_DIR'); alerting by ntfy only"
        return 0
    fi
    if output=$(cd "$LEDGER_DIR" && "$LEDGER_WRAPPER" -- bd comment "$LEDGER_EPIC" "$text" 2>&1); then
        log "recorded the alert as a comment on $LEDGER_EPIC"
    else
        log "WARNING: could not comment on $LEDGER_EPIC; alerting by ntfy only: ${output//$'\n'/; }"
    fi
}

check_filesystem() {
    local filesystem=$1 threshold=$2 key=$3 used available marker response_code curl_status
    read -r used available < <(filesystem_values "$filesystem")
    [[ -n ${used:-} && -n ${available:-} ]] || { log "WARNING: cannot measure $filesystem"; return 0; }
    ((used >= threshold)) || return 0
    marker="$STATE_DIR/$key.last-notified"
    may_notify "$marker" || { log "$filesystem remains at ${used}%; repeat interval holds"; return 0; }
    local message
    message="$filesystem used ${used}%, ${available} KiB free on $(hostname). Owner: $OWNER. Runbook: $RUNBOOK (section 'Disk full: first steps')"
    record_in_ledger "Dev host capacity alert: $message"
    response_code=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
        "${ntfy_auth_args[@]}" -H 'Title: Dev host capacity alert' \
        -d "$message" "$SERVER/$TOPIC")
    curl_status=$?
    if [[ $response_code == 429 ]]; then
        log "WARNING: ntfy publication was rate limited for $filesystem"
    elif ((curl_status != 0)); then
        log "WARNING: ntfy publication failed for $filesystem"
    # curl itself always writes an HTTP status when it contacted the server.
    # Keep accepting an empty value from the established local curl wrapper,
    # which reports successful delivery only through its zero exit status.
    elif [[ -z $response_code || $response_code =~ ^2[0-9][0-9]$ ]]; then
        date -u +%s >"$marker"
        log "alerted for $filesystem: ${used}% used, ${available} KiB free"
    else
        log "WARNING: ntfy publication failed for $filesystem"
    fi
}

mkdir -p "$STATE_DIR"
if [[ -z $TOPIC ]]; then
    log "WARNING: no ntfy topic configured; capacity check cannot alert"
    exit 0
fi
configure_ntfy_auth
check_filesystem / "$ROOT_THRESHOLD" root
check_filesystem /tmp "$TMP_THRESHOLD" tmp
