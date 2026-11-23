#!/usr/bin/env bash
# Apply merged CI-stack changes to every CI host (livespec-dev-tooling-ctete5).
#
# Runs on the control-node role host from a timer. Compares master's tip with the
# SHA last applied (a file written only after a drift-zero read-back passed), and
# for a range that touches the CI stack:
#   * HOLDS the whole range, applying nothing, when it touches a credential
#     manifest (credential-manifests.list), and signals once per hold;
#   * otherwise runs the committed scoped apply (`--tags ci_placement` when only
#     placement files changed, else `--tags ci_converge_unit`), then reads drift
#     back and requires changed=0 for every host before moving the SHA.
# A failed apply or read-back leaves the SHA unmoved so the next tick retries;
# the third consecutive failure signals the maintainer. `apply.disabled` in the
# state directory is the kill switch, checked first and between steps.
#
#   apply-merged-ci-changes.sh            one tick
#   apply-merged-ci-changes.sh --seed SHA record SHA as applied (an owner's apply ran)
#
# Exit: 0 nothing to do or applied; 1 apply or read-back failed; 3 not seeded; 4 held.
set -euo pipefail

STATE_DIR="${CONVERGE_TRIGGER_STATE_DIR:-/var/lib/ci-converge-trigger}"
CHECKOUT="${CONVERGE_TRIGGER_CHECKOUT:-${STATE_DIR}/checkout}"
REPO_URL="${CONVERGE_TRIGGER_REPO_URL:-https://github.com/livespec-ai/livespec-dev-tooling.git}"
BRANCH="${CONVERGE_TRIGGER_BRANCH:-master}"
APPLY_CMD="${CONVERGE_TRIGGER_APPLY_CMD:-just ansible-apply ansible/ci-pool.yml}"
DRIFT_CMD="${CONVERGE_TRIGGER_DRIFT_CMD:-just ansible-drift ansible/ci-pool.yml}"
SIGNAL_CMD="${CONVERGE_TRIGGER_SIGNAL_CMD:-}"
MAX_FAILURES="${CONVERGE_TRIGGER_MAX_FAILURES:-3}"

mkdir -p "${STATE_DIR}/records"
last_file="${STATE_DIR}/last-applied-sha"
fail_file="${STATE_DIR}/consecutive-failures"
hold_file="${STATE_DIR}/hold-key"
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { printf '%s ci-converge-trigger: %s\n' "$(now)" "$*"; }
signal() {
  say "SIGNAL: $*"
  if [ -n "${SIGNAL_CMD}" ]; then ${SIGNAL_CMD} "$*" || say "signal command failed"; fi
  printf '%s %s\n' "$(now)" "$*" >>"${STATE_DIR}/signals.log"
}
disabled() { [ -e "${STATE_DIR}/apply.disabled" ]; }
record() { # record <outcome> <last> <master> <tags> <detail>
  local f
  f="${STATE_DIR}/records/$(date -u +%Y%m%dT%H%M%SZ)-$1.json"
  printf '{"outcome":"%s","applied_from":"%s","master":"%s","tags":"%s","detail":"%s","at":"%s"}\n' \
    "$1" "$2" "$3" "$4" "${5//\"/\'}" "$(now)" >"$f"
}

if [ "${1:-}" = "--seed" ]; then
  [ -n "${2:-}" ] || { echo "usage: $0 --seed SHA" >&2; exit 2; }
  printf '%s\n' "$2" >"$last_file"; echo 0 >"$fail_file"; rm -f "$hold_file"
  say "seeded last-applied-sha=$2"; exit 0
fi

if disabled; then say "apply.disabled present; doing nothing"; exit 0; fi

if [ ! -d "${CHECKOUT}/.git" ]; then git clone --quiet "${REPO_URL}" "${CHECKOUT}"; fi
git -C "${CHECKOUT}" fetch --quiet origin "${BRANCH}"
git -C "${CHECKOUT}" checkout --quiet --detach FETCH_HEAD
master="$(git -C "${CHECKOUT}" rev-parse HEAD)"

if [ ! -s "$last_file" ]; then
  say "not seeded: no last-applied-sha. Run the owner's apply, then: $0 --seed <sha>"; exit 3
fi
last="$(tr -d '[:space:]' <"$last_file")"
[ "$last" != "$master" ] || { say "up to date at ${master}"; exit 0; }

changed="$(git -C "${CHECKOUT}" diff --name-only "$last" "$master" -- ci-runner ansible/ci-pool.yml ansible/roles/ci_converge_unit)"
if [ -z "$changed" ]; then
  printf '%s\n' "$master" >"$last_file"; say "no CI-stack path changed in ${last}..${master}; advanced"; exit 0
fi

list_paths() { grep -v -E '^[[:space:]]*(#|$)' "${CHECKOUT}/ci-runner/converge-trigger/$1" || true; }
held=""
while IFS= read -r p; do
  [ -n "$p" ] || continue
  while IFS= read -r c; do
    case "$c" in
      "$p"|"$p"*) if [ "${p%/}" = "$p" ] && [ "$c" != "$p" ]; then continue; fi; held="${held}${c} " ;;
    esac
  done <<<"$changed"
done <<<"$(list_paths credential-manifests.list)"
if [ -n "$held" ]; then
  key="${last}..${master}:${held}"
  if [ "$(cat "$hold_file" 2>/dev/null || true)" != "$key" ]; then
    signal "HOLD ${last}..${master}: credential manifest(s) changed: ${held}. Nothing applied; the owner's apply releases it, then seed with: apply-merged-ci-changes.sh --seed ${master}"
    printf '%s\n' "$key" >"$hold_file"
  fi
  record held "$last" "$master" "" "$held"
  exit 4
fi
rm -f "$hold_file"

tags="ci_placement"
placement="$(list_paths placement-files.list)"
while IFS= read -r c; do
  [ -n "$c" ] || continue
  grep -qxF -- "$c" <<<"$placement" || { tags="ci_converge_unit"; break; }
done <<<"$changed"

fail() {
  local n
  n=$(( $(cat "$fail_file" 2>/dev/null || echo 0) + 1 ))
  echo "$n" >"$fail_file"
  record failed "$last" "$master" "$tags" "$1"
  say "FAILED (${n} consecutive): $1"
  if [ "$n" -ge "$MAX_FAILURES" ]; then signal "apply failed ${n} times in a row for ${last}..${master} (--tags ${tags}): $1"; fi
  exit 1
}

say "applying ${last}..${master} with --tags ${tags}"
disabled && { say "apply.disabled appeared; stopping"; exit 0; }
( cd "${CHECKOUT}" && ${APPLY_CMD} --tags "${tags}" ) || fail "apply exited non-zero"
disabled && { say "apply.disabled appeared; stopping before the read-back"; exit 0; }
recap="$( cd "${CHECKOUT}" && ${DRIFT_CMD} --tags "${tags}" 2>&1 )" || fail "drift read-back exited non-zero"
bad="$(grep -E '^[^ ]+[[:space:]]*:[[:space:]]+ok=' <<<"$recap" | grep -v -E 'changed=0[[:space:]]' || true)"
hosts="$(grep -c -E '^[^ ]+[[:space:]]*:[[:space:]]+ok=' <<<"$recap" || true)"
[ "${hosts}" -gt 0 ] || fail "drift read-back printed no play recap"
[ -z "$bad" ] || fail "drift read-back not zero: ${bad//$'\n'/; }"

had_trouble=false
[ "$(cat "$fail_file" 2>/dev/null || echo 0)" -gt 0 ] && had_trouble=true
printf '%s\n' "$master" >"$last_file"; echo 0 >"$fail_file"
record applied "$last" "$master" "$tags" "changed=0 on ${hosts} host(s)"
say "applied ${last}..${master} (--tags ${tags}); drift changed=0 on ${hosts} host(s)"
if [ "$had_trouble" = true ]; then signal "recovered: ${last}..${master} applied, drift changed=0"; fi
