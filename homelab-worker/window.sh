#!/usr/bin/env bash
# window.sh <action> <host> — the M4 window route's ON-HOST half
# (livespec-dev-tooling-nn4yxt). ansible/homelab-worker-window.yml runs it on
# the worker's Mac from the delivered release directory, with PATH, the
# cluster-reaching kubectl and the join values set from inventory. It wraps
# remove-worker.sh, join-worker.sh and departure-drill.sh and fences each to
# the one node <host>-homelab-worker.
#
# Actions (each acts on that node only):
#   snapshot  record gates-cq (kubectl get clusterqueue gates-cq -o json) under
#             WINDOW_STATE_DIR with the UTC time it was taken, as the window's
#             before-state. Refuses to overwrite an existing snapshot, so the
#             before-state is never replaced by a mid-window state.
#   archive-snapshot  move a before-snapshot that has gone stale (older than
#             WINDOW_MAX_AGE_SECONDS) or cannot be read to gates-cq-before.<UTC>.json
#             in WINDOW_STATE_DIR, so a new window can take its own snapshot. It
#             touches no cluster state and not the node. It refuses a snapshot still
#             inside the limit (it is a live window's before-state) unless
#             WINDOW_FORCE_ARCHIVE equals the node name. With no snapshot it says so
#             and exits zero.
#   join      join-worker.sh <host> --api-server $WINDOW_API_SERVER --server-ca
#             $WINDOW_SERVER_CA. Refuses unless a snapshot taken for this window
#             exists and is younger than WINDOW_MAX_AGE_SECONDS (default 86400),
#             because the join runs converge-worker-queues.sh, which patches gates-cq.
#   drill     departure-drill.sh <host> --confirm-depart <node>
#   remove    remove-worker.sh <host> (it refuses an uncordoned node)
#   check     the revert TRIGGER: the node must be Ready within
#             WINDOW_BOUND_SECONDS (a failed read is retried 3 times and is not
#             "not Ready"), and no non-terminal pod a DaemonSet does not own may
#             be bound to it. Either failure runs `revert` and exits 3.
#   stop      take the worker out of service WITHOUT deleting its Node: the node must be
#             registered and cordoned, and no Running or Pending pod a DaemonSet does not own
#             may be bound to it (it never evicts). It stops the kubelet inside the worker
#             container, then stops the VM unit homelab-worker-container.service that
#             supervises the container (a bare docker stop is restarted by it). The Node object, the kubelet's credentials
#             and the worker queues are left as they are, so `start` returns the worker.
#   start     the reversal of stop: start the worker container and its kubelet. It does not
#             uncordon (that is ansible/k3s-window-drain.yml, action uncordon).
#   revert    cordon the node, depart it (remove-worker.sh), and ONLY IF THE
#             DEPARTURE SUCCEEDED restore gates-cq from the snapshot, then archive
#             the snapshot as gates-cq-before.<UTC>.json. remove-worker.sh refuses
#             while a Running or Pending pod no DaemonSet owns is on the node, and it
#             never evicts. So a revert triggered by such a pod ends INCOMPLETE,
#             exits non-zero, and leaves the node cordoned and enrolled and gates-cq
#             as it is. The operator then moves the work (ansible/k3s-window-drain.yml,
#             action evacuate, or waits for it) and re-runs revert.
#
# The restore is a JSON patch of the one thing converge-worker-queues.sh changes,
# the flavor list of gates-cq's cpu resource group, taken from the snapshot, so
# any other edit made to gates-cq since the snapshot is kept. It refuses when the
# snapshot names a ResourceFlavor that no longer exists. kubectl runs through
# remote-kubectl.sh, which forwards only arguments and stdin, so nothing here
# passes a local file path to kubectl.
#
# Environment: WINDOW_NODE_CONFIRM (must equal <host>-homelab-worker),
# WINDOW_STATE_DIR, WINDOW_API_SERVER, WINDOW_SERVER_CA, WINDOW_BOUND_SECONDS
# (default 600), WINDOW_POLL_SECONDS (default 15), WINDOW_MAX_AGE_SECONDS,
# WINDOW_FORCE_ARCHIVE (archive-snapshot only), WINDOW_RETRY_SECONDS (default 2), WINDOW_SCRIPTS_DIR (default: this script's
# directory), HOMELAB_WORKER_HOSTS_DIR.
# Written for bash 3.2 (the macOS system bash); no mapfile.
set -euo pipefail

prog="window"
hw="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
scripts="${WINDOW_SCRIPTS_DIR:-$hw}"
hosts_dir="${HOMELAB_WORKER_HOSTS_DIR:-$hw/hosts}"
bound="${WINDOW_BOUND_SECONDS:-600}"
poll="${WINDOW_POLL_SECONDS:-15}"
max_age="${WINDOW_MAX_AGE_SECONDS:-86400}"
retry_sleep="${WINDOW_RETRY_SECONDS:-2}"

die() {
  printf '%s: %s\n' "$prog" "$*" >&2
  exit 1
}
say() {
  printf '%s: %s\n' "$prog" "$*"
}

[ "$#" -eq 2 ] || die "usage: $prog snapshot|archive-snapshot|join|drill|remove|stop|start|check|revert <host>"
action="$1"
host="$2"
case "$host" in
  *[!a-z0-9-]* | -* | "") die "host '$host' is not a valid host name" ;;
esac
[ -f "$hosts_dir/$host.env" ] || die "host '$host' is not declared in homelab-worker/hosts/"
node="$host-homelab-worker"
[ "${WINDOW_NODE_CONFIRM:-}" = "$node" ] ||
  die "WINDOW_NODE_CONFIRM is '${WINDOW_NODE_CONFIRM:-}', not '$node': refusing, nothing was changed"
state="${WINDOW_STATE_DIR:-}"
[ -n "$state" ] || die "WINDOW_STATE_DIR is not set"
snap="$state/gates-cq-before.json"

# ready: 0 when the node's Ready condition is True, 1 when it is not True, 2 when
# the node could not be read in 3 tries (a failed read is not "not Ready").
ready() {
  local out i=0
  while [ "$i" -lt 3 ]; do
    if out="$(kubectl get node "$node" -o json 2>/dev/null)"; then
      printf '%s' "$out" | python3 -c '
import json, sys
n = json.load(sys.stdin)
sys.exit(0 if any(c.get("type") == "Ready" and c.get("status") == "True"
                  for c in n.get("status", {}).get("conditions", [])) else 1)' && return 0
      return 1
    fi
    i=$((i + 1))
    [ "$i" -ge 3 ] || sleep "$retry_sleep"
  done
  return 2
}

# foreign_pods: namespace/name of each non-terminal pod bound to the node that no
# DaemonSet owns (a pod with no owner counts; Succeeded and Failed pods do not,
# as in remove-worker.sh). Fails loudly when the read fails.
foreign_pods() {
  local out
  out="$(kubectl get pods --all-namespaces --field-selector "spec.nodeName=$node" -o json)" ||
    return 1
  printf '%s' "$out" | python3 -c '
import json, sys
for p in json.load(sys.stdin).get("items", []):
    if p.get("status", {}).get("phase") in ("Succeeded", "Failed"):
        continue
    if not any(o.get("kind") == "DaemonSet" for o in p["metadata"].get("ownerReferences", [])):
        print("%s/%s" % (p["metadata"]["namespace"], p["metadata"]["name"]))'
}

do_snapshot() {
  mkdir -p "$state"
  [ ! -e "$snap" ] || die "a before-snapshot already exists at $snap; refusing to replace it (revert the window, or run the archive-snapshot action to move it aside)"
  local out
  out="$(kubectl get clusterqueue gates-cq -o json)" || die "could not read gates-cq; no snapshot was taken"
  printf '%s' "$out" | python3 -c '
import datetime, json, sys, time
q = json.load(sys.stdin)
for k in ("resourceVersion", "uid", "creationTimestamp", "generation", "managedFields", "selfLink"):
    q["metadata"].pop(k, None)
q.pop("status", None)
now = datetime.datetime.now(datetime.timezone.utc)
json.dump({"taken_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "taken_at_epoch": int(time.time()),
           "queue": q}, sys.stdout, indent=1)' >"$snap.tmp"
  mv "$snap.tmp" "$snap"
  say "snapshot of gates-cq written to $snap"
}

# snapshot_problem: prints why the window has no usable before-snapshot, else nothing.
snapshot_problem() {
  [ -f "$snap" ] || { echo "no before-snapshot at $snap"; return 0; }
  python3 -c '
import json, sys, time
age = time.time() - json.load(open(sys.argv[1]))["taken_at_epoch"]
if age > int(sys.argv[2]):
    print("the before-snapshot at %s is %d s old, over the %s s window limit" % (sys.argv[1], age, sys.argv[2]))' "$snap" "$max_age"
}

# do_archive_snapshot: see the archive-snapshot action above. It reads the
# snapshot's age only and never calls kubectl.
do_archive_snapshot() {
  local problem="" stamp
  [ -f "$snap" ] || { say "no before-snapshot at $snap; nothing to archive"; return 0; }
  problem="$(snapshot_problem 2>/dev/null)" || problem="the before-snapshot at $snap cannot be read"
  if [ -z "$problem" ] && [ "${WINDOW_FORCE_ARCHIVE:-}" != "$node" ]; then
    die "refusing to archive: the before-snapshot at $snap is inside the ${max_age} s window limit, so it is a live window's before-state (WINDOW_FORCE_ARCHIVE=$node forces it); nothing was changed"
  fi
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  mv "$snap" "$state/gates-cq-before.$stamp.json"
  say "archived the before-snapshot as $state/gates-cq-before.$stamp.json (${problem:-forced while fresh})"
}

# restore_queue: put back the flavor list of gates-cq's cpu resource group as the
# snapshot recorded it, leaving everything else on gates-cq alone. Refuses, with
# the queue untouched, on a missing or stale snapshot, or when the snapshot names
# a ResourceFlavor that no longer exists (converge-worker-queues.sh deletes the
# retired gates-worker-arm64-flavor, and a queue naming a missing flavor is
# inactive).
restore_queue() {
  local problem flavor live patch
  problem="$(snapshot_problem)"
  [ -z "$problem" ] || { say "RESTORE FAILED: $problem"; return 1; }
  for flavor in $(python3 -c '
import json, sys
q = json.load(open(sys.argv[1]))["queue"]
for g in q["spec"]["resourceGroups"]:
    for f in g["flavors"]:
        print(f["name"])' "$snap" | sort -u); do
    kubectl get resourceflavor "$flavor" >/dev/null 2>&1 || {
      say "RESTORE FAILED: the snapshot names ResourceFlavor $flavor, which does not exist; gates-cq was left as it is"
      return 1
    }
  done
  live="$(kubectl get clusterqueue gates-cq -o json)" || { say "RESTORE FAILED: could not read gates-cq"; return 1; }
  patch="$(printf '%s' "$live" | python3 -c '
import json, sys
live = json.load(sys.stdin)
snap = json.load(open(sys.argv[1]))["queue"]
def cpu(q):
    return next(i for i, g in enumerate(q["spec"]["resourceGroups"]) if "cpu" in g.get("coveredResources", []))
want = snap["spec"]["resourceGroups"][cpu(snap)]["flavors"]
print(json.dumps([{"op": "replace", "path": "/spec/resourceGroups/%d/flavors" % cpu(live), "value": want}]))' "$snap")" ||
    { say "RESTORE FAILED: could not build the patch"; return 1; }
  kubectl patch clusterqueue gates-cq --type=json -p "$patch" >/dev/null || { say "RESTORE FAILED: kubectl patch of gates-cq failed"; return 1; }
  say "gates-cq cpu-group flavors restored from $snap"
}

in_vm() {
  limactl shell --workdir / "$node" sudo "$@"
}

# do_stop: see the stop action above. Every read is checked and nothing is changed before
# they pass; it never calls kubectl delete.
do_stop() {
  local present foreign running
  present="$(kubectl get node "$node" --ignore-not-found -o 'jsonpath={.metadata.name} {.spec.unschedulable}')" ||
    die "could not read Node $node; nothing was changed"
  [ "$present" = "$node true" ] ||
    die "Node $node is not registered and cordoned (read '$present'); cordon it first (ansible/k3s-window-drain.yml, action cordon). Nothing was changed"
  foreign="$(kubectl get pods --all-namespaces --field-selector "spec.nodeName=$node" -o json)" ||
    die "could not read the pods on $node; nothing was changed"
  foreign="$(printf '%s' "$foreign" | python3 -c '
import json, sys
for p in json.load(sys.stdin).get("items", []):
    if p.get("status", {}).get("phase") not in ("Running", "Pending") or any(
            o.get("kind") == "DaemonSet" for o in p["metadata"].get("ownerReferences", [])):
        continue
    print("%s/%s" % (p["metadata"]["namespace"], p["metadata"]["name"]))')"
  [ -z "$foreign" ] ||
    die "Node $node still has running or pending pods no DaemonSet owns: $(printf '%s' "$foreign" | tr '\n' ' '). Let them finish or move them first. Nothing was changed"
  in_vm true || die "could not reach VM $node through limactl; nothing was changed"
  if running="$(in_vm docker inspect -f '{{.State.Running}}' "$node" 2>/dev/null)" && [ "$running" = true ]; then
    in_vm docker exec "$node" systemctl stop kubelet || die "could not stop the kubelet in container $node; the container was left running"
    say "kubelet stopped in container $node"
  fi
  # The VM's homelab-worker-container.service supervises the container with Restart=on-failure,
  # so a bare `docker stop` makes `docker start -a` exit non-zero and systemd starts it again
  # within seconds (measured 2026-11-24). Stop the unit; its ExecStop is the docker stop.
  in_vm systemctl stop homelab-worker-container.service || die "could not stop homelab-worker-container.service in VM $node"
  running="$(in_vm docker inspect -f '{{.State.Running}}' "$node" 2>/dev/null)" || running=false
  [ "$running" != true ] || die "container $node is still running after its unit was stopped"
  # Disabled too, so the stop survives a reboot of the VM; start re-enables it.
  in_vm systemctl disable homelab-worker-container.service || die "could not disable homelab-worker-container.service in VM $node"
  say "container $node stopped through homelab-worker-container.service; Node $node is still registered and cordoned"
}

# do_start: the reversal of do_stop. Starts the container and its kubelet; never uncordons.
do_start() {
  in_vm true || die "could not reach VM $node through limactl; nothing was changed"
  in_vm systemctl enable homelab-worker-container.service || die "could not enable homelab-worker-container.service in VM $node"
  in_vm systemctl start homelab-worker-container.service || die "could not start homelab-worker-container.service in VM $node"
  in_vm docker exec "$node" systemctl start kubelet || die "could not start the kubelet in container $node"
  say "container $node and its kubelet started; Node $node is still cordoned until the uncordon action lifts it"
}

do_revert() {
  say "REVERT: departing $node and restoring gates-cq"
  kubectl cordon "$node" >/dev/null || say "could not cordon $node; the removal below will refuse an uncordoned node"
  if ! "$scripts/remove-worker.sh" "$host"; then
    say "REVERT INCOMPLETE: the departure of $node failed or was refused (it never evicts). $node is still enrolled and cordoned, and gates-cq was NOT restored. Move the work off it (ansible/k3s-window-drain.yml, action evacuate, or wait for it to finish) and run revert again."
    return 1
  fi
  restore_queue || { say "REVERT INCOMPLETE: $node departed but gates-cq was not restored; fix the cause above and run revert again"; return 1; }
  mv "$snap" "$state/gates-cq-before.$(date -u +%Y%m%dT%H%M%SZ).json"
  say "REVERT: complete; the snapshot was archived under $state"
}

do_check() {
  local deadline foreign rc
  deadline=$(($(date +%s) + bound))
  while :; do
    foreign="$(foreign_pods)" || die "could not read the pods on $node; no verdict"
    if [ -n "$foreign" ]; then
      say "TRIGGER: non-DaemonSet pod(s) landed on $node:"
      printf '%s\n' "$foreign" | sed "s/^/$prog:   /"
      do_revert || true
      exit 3
    fi
    rc=0
    ready || rc=$?
    if [ "$rc" -eq 0 ]; then
      say "ok: $node is Ready and carries only DaemonSet pods"
      return 0
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
      if [ "$rc" -eq 2 ]; then
        say "TRIGGER: $node could not be read within ${bound}s"
      else
        say "TRIGGER: $node is not Ready within ${bound}s"
      fi
      do_revert || true
      exit 3
    fi
    sleep "$poll"
  done
}

case "$action" in
  snapshot) do_snapshot ;;
  archive-snapshot) do_archive_snapshot ;;
  join)
    problem="$(snapshot_problem)"
    [ -z "$problem" ] || die "refusing to join: $problem (run the snapshot action for this window first)"
    [ -n "${WINDOW_API_SERVER:-}" ] || die "WINDOW_API_SERVER is not set"
    [ -n "${WINDOW_SERVER_CA:-}" ] || die "WINDOW_SERVER_CA is not set"
    exec "$scripts/join-worker.sh" "$host" --api-server "$WINDOW_API_SERVER" --server-ca "$WINDOW_SERVER_CA"
    ;;
  drill) exec "$scripts/departure-drill.sh" "$host" --confirm-depart "$node" ;;
  remove) exec "$scripts/remove-worker.sh" "$host" ;;
  stop) do_stop ;;
  start) do_start ;;
  check) do_check ;;
  revert) do_revert ;;
  *) die "unknown action '$action'" ;;
esac
