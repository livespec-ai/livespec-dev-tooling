"""The adaptive JIT runner admission budget of `SPECIFICATION/non-functional-requirements.md`
— the three static terms of the min(), held together.

The section's admission formula is `min(queued jobs, doubled repository logical
ceiling, fair share of remaining host-wide capacity)` under a physical invariant:
"The physical host-wide cap remains exactly 482 active runners; no configuration
or recovery path may derive or admit 964 runners."

`DERIVATION.md` beside the manifests records where each term lives, and the
mapping is what makes the formula real: the first term is dynamic (ARC's
listener counts assigned jobs and needs no configuration), and the other THREE
are static files that bound it —

- `doubled repository logical ceiling` is a scale set's `maxRunners`, bounded
  since 2026-09-06 to `max(2 x nominalQuota, 6)` except where DERIVATION.md
  records an exception;
- `fair share of remaining host-wide capacity` is that repository's ClusterQueue
  `nominalQuota` inside the one cohort;
- the physical cap is the node's `ci-runner.io/churn-slot` capacity, which the
  node's own profile carries as `ADMISSION_CAPACITY_C`.

Each term is a hand-maintained number in a DIFFERENT file, and the relations
between them are what the section states rather than what any one file says. So
every way they can drift apart is silent, and each drift breaks a named clause:

- **A `maxRunners` that outgrows its quota** breaks "never so large that a
  backlog is materialized as pending admission objects the host's control plane
  must keep reconciling". The scale set still admits; the surplus becomes
  pending pods the scheduler re-reconciles forever, which is precisely the cost
  the clause says must be paid at the forge instead.
- **A `maxRunners` that shrinks to its quota** breaks the opposite clause,
  "Repositories MAY fairly borrow unused capacity": with the ceiling equal to
  the fair share, idle capacity elsewhere in the cohort is unreachable. The
  bound is two-sided for that reason, and this is the direction `DERIVATION.md`
  records the earlier "one number" reading getting wrong.
- **Quotas that no longer sum to the pool's total capacity** break the
  fair-share term itself: over-subscribed, the guaranteed floors are not
  guaranteed; under-subscribed, capacity the pool has is unreachable by anyone.
  Since the two-node opening (DERIVATION.md "The derivation at C = 44 — the
  two-node pool") churn-slot capacity is per-node while the cohort quota is
  cluster-wide, so the sum is taken across every node's `ADMISSION_CAPACITY_C`.

None of the three raises an error. A wrong number is a valid manifest, applies
cleanly, and produces a pool that admits the wrong amount of work.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__: list[str] = []

_REPO_ROOT = Path(__file__).resolve().parents[2]
_KUEUE_DIR = _REPO_ROOT / "ci-runner" / "k3s" / "phase2" / "kueue"
_DERIVATION = _KUEUE_DIR / "DERIVATION.md"
_ARC_DIR = _REPO_ROOT / "ci-runner" / "k3s" / "phase2" / "arc"
_PROFILES_DIR = _REPO_ROOT / "ci-runner" / "k3s" / "phase0-bare-metal" / "profiles"

# The one cohort the fair-share term is apportioned within.
_COHORT = "fleet-ci-runner-pool"
_CHURN_SLOT = "ci-runner.io/churn-slot"
_FLEET_FLAVOR = "churn-slot-flavor"
_WORKER_QUOTA_TEMPLATE = "@WORKER_CHURN_SLOTS@"

# The bound the section's "small multiple ... and any floor" clause resolves to
# for this pool, recorded with the pool's admission derivation as the section
# requires: `max(MULTIPLE x nominalQuota, FLOOR)`.
_CEILING_MULTIPLE = 2
_CEILING_FLOOR = 6

_EXCEPTIONS_HEADING = "### Recorded exceptions to the rule"

# The physical invariant, stated in the section itself.
_PHYSICAL_CAP = 482
_FORBIDDEN_DOUBLING = _PHYSICAL_CAP * 2

_DOC_SEPARATOR = re.compile(r"^---$", re.MULTILINE)
_KIND = re.compile(r"^kind:\s*(?P<kind>\S+)$", re.MULTILINE)
_NAME = re.compile(r"^  name:\s*(?P<name>\S+)", re.MULTILINE)
_COHORT_NAME = re.compile(r"^  cohortName:\s*(?P<cohort>\S+)", re.MULTILINE)
_CLUSTER_QUEUE = re.compile(r"^  clusterQueue:\s*(?P<cq>\S+)", re.MULTILINE)
_LENDING_LIMIT = re.compile(r"^\s+lendingLimit:\s*(?P<limit>\S+)\s*$", re.MULTILINE)
_MAX_RUNNERS = re.compile(r"^\s*maxRunners:\s*(?P<max>\d+)\s*$", re.MULTILINE)
_QUEUE_NAME = re.compile(r"^\s*kueue\.x-k8s\.io/queue-name:\s*(?P<lq>\S+)\s*$", re.MULTILINE)
_ADMISSION_CAPACITY = re.compile(r"^ADMISSION_CAPACITY_C=(?P<capacity>\d+)\s*$", re.MULTILINE)
_FLAVOR_NAME = re.compile(r"^ {8}- name:\s*(?P<flavor>\S+)\s*$", re.MULTILINE)
_CHURN_RESOURCE_NAME = re.compile(
    r'^ {12}- name:\s*["\']?ci-runner\.io/churn-slot["\']?\s*$', re.MULTILINE
)
_RESOURCE_FIELD = re.compile(
    r"^ {14}(?P<field>nominalQuota|borrowingLimit):\s*(?P<value>\S+)\s*$", re.MULTILINE
)


def _documents() -> list[str]:
    """Every YAML document across the committed ClusterQueue manifests."""
    return [
        document
        for path in sorted(_KUEUE_DIR.rglob("cluster-queue-*.yaml"))
        for document in _DOC_SEPARATOR.split(path.read_text(encoding="utf-8"))
    ]


def _churn_slot_flavors(document: str, member: str) -> dict[str, tuple[str, str | None]]:
    """Read one ClusterQueue's churn-slot quota details without parsing templates as YAML."""
    flavors: dict[str, tuple[str, str | None]] = {}
    matches = list(_FLAVOR_NAME.finditer(document))
    for index, flavor in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(document)
        block = document[flavor.end() : end]
        churn_resource = _CHURN_RESOURCE_NAME.search(block)
        if churn_resource is None:
            continue
        next_resource = re.search(r"^ {12}- name:\s*", block[churn_resource.end() :], re.MULTILINE)
        resource_end = (
            churn_resource.end() + next_resource.start()
            if next_resource is not None
            else len(block)
        )
        fields = {
            field.group("field"): field.group("value")
            for field in _RESOURCE_FIELD.finditer(block[churn_resource.end() : resource_end])
        }
        assert "nominalQuota" in fields, (
            f"a `{_COHORT}` member's `{_CHURN_SLOT}` flavor needs a nominalQuota; "
            f"member={member} flavor={flavor.group('flavor')}"
        )
        flavors[flavor.group("flavor")] = (fields["nominalQuota"], fields.get("borrowingLimit"))
    return flavors


def _cohort_flavor_quotas(
    documents: list[str] | None = None,
) -> dict[str, dict[str, tuple[str, str | None]]]:
    """Every cohort member's churn-slot quota and borrowing limit, keyed by flavor.

    The worker ClusterQueue is a template, so its quota is intentionally retained
    as text rather than forced through the integer-only fleet arithmetic.
    """
    members: dict[str, dict[str, tuple[str, str | None]]] = {}
    for document in _documents() if documents is None else documents:
        kind = _KIND.search(document)
        cohort = _COHORT_NAME.search(document)
        name = _NAME.search(document)
        if kind is None or kind.group("kind") != "ClusterQueue":
            continue
        if cohort is None or cohort.group("cohort") != _COHORT:
            continue
        assert name is not None, f"a `{_COHORT}` member must carry a name; document={document!r}"
        flavors = _churn_slot_flavors(document, name.group("name"))
        assert flavors, (
            f"a `{_COHORT}` member must carry one `{_CHURN_SLOT}` nominalQuota; "
            f"member={name.group('name')}"
        )
        members[name.group("name")] = flavors
    return members


def _cohort_quotas() -> dict[str, int]:
    """Each fleet-flavor cohort member's churn-slot `nominalQuota`."""
    quotas: dict[str, int] = {}
    for member, flavors in _cohort_flavor_quotas().items():
        if _FLEET_FLAVOR not in flavors:
            continue
        quota, _ = flavors[_FLEET_FLAVOR]
        assert quota.isdecimal(), (
            f"the `{_FLEET_FLAVOR}` quota must be a committed integer; "
            f"member={member} quota={quota}"
        )
        quotas[member] = int(quota)
    return quotas


def _local_queue_targets() -> dict[str, str]:
    """Each committed LocalQueue name mapped to the ClusterQueue it feeds."""
    targets: dict[str, str] = {}
    for document in _documents():
        kind = _KIND.search(document)
        name = _NAME.search(document)
        cluster_queue = _CLUSTER_QUEUE.search(document)
        if kind is not None and kind.group("kind") == "LocalQueue":
            assert (
                name is not None and cluster_queue is not None
            ), f"a LocalQueue must name itself and its ClusterQueue; document={document!r}"
            targets[name.group("name")] = cluster_queue.group("cq")
    return targets


def _scale_set_ceilings() -> dict[str, tuple[str, int]]:
    """Each queue-routed scale set's ClusterQueue mapped to (values file, maxRunners).

    A values file that names no LocalQueue, or declares no ceiling, is not a
    routed scale set and contributes nothing — that is how the committed
    template and the host-unique release stay out of the arithmetic.
    """
    targets = _local_queue_targets()
    ceilings: dict[str, tuple[str, int]] = {}
    for path in sorted(_ARC_DIR.glob("values-*.yaml")):
        source = path.read_text(encoding="utf-8")
        queue = _QUEUE_NAME.search(source)
        ceiling = _MAX_RUNNERS.search(source)
        if queue is None or ceiling is None:
            continue
        local_queue = queue.group("lq")
        ceilings[targets.get(local_queue, local_queue)] = (path.name, int(ceiling.group("max")))
    return ceilings


def _recorded_exception_ceilings() -> dict[str, tuple[int, int, int]]:
    """Read exception rows from DERIVATION.md, keyed by their ClusterQueue.

    The table is the source of truth for every departure from the bounded
    multiple; values files establish the row's repository-to-queue routing.
    """
    section = _DERIVATION.read_text(encoding="utf-8").split(_EXCEPTIONS_HEADING, 1)[1]
    lines = section.splitlines()
    table_start = next(index for index, line in enumerate(lines) if line.startswith("|"))
    table = []
    for line in lines[table_start:]:
        if not line.startswith("|"):
            break
        table.append(line)
    headers = [cell.strip().strip("`") for cell in table[0].strip("|").split("|")]
    required = {"Repository", "nominalQuota", "Rule value", "maxRunners"}
    assert required <= set(headers), f"recorded-exceptions table needs {sorted(required)}"
    rows = [
        dict(
            zip(
                headers,
                (cell.strip().strip("`") for cell in line.strip("|").split("|")),
                strict=False,
            )
        )
        for line in table[2:]
    ]

    targets = _local_queue_targets()
    exceptions: dict[str, tuple[int, int, int]] = {}
    for row in rows:
        repository = row["Repository"]
        values_path = _ARC_DIR / f"values-{repository}.yaml"
        source = values_path.read_text(encoding="utf-8")
        queue = _QUEUE_NAME.search(source)
        assert queue is not None, f"{values_path.name} must route through a LocalQueue"
        cluster_queue = targets.get(queue.group("lq"), queue.group("lq"))
        assert cluster_queue not in exceptions, (
            f"each ClusterQueue may have one recorded ceiling exception; "
            f"clusterQueue={cluster_queue}"
        )
        exceptions[cluster_queue] = (
            int(row["nominalQuota"]),
            int(row["Rule value"]),
            int(row["maxRunners"].strip("*")),
        )
    return exceptions


def test_every_repository_ceiling_is_the_bounded_multiple_of_its_fair_share() -> None:
    """`maxRunners == max(2 x nominalQuota, 6)`, or its recorded exception, in both directions."""
    quotas = _cohort_quotas()
    ceilings = _scale_set_ceilings()
    assert quotas and ceilings, (
        f"the cohort and its scale sets must both be committed; quotas={sorted(quotas)} "
        f"ceilings={sorted(ceilings)}"
    )
    unrouted = sorted(set(quotas) - set(ceilings))
    assert not unrouted, (
        f"every cohort member's fair share must belong to a scale set that can spend it; "
        f"a quota with no scale set routed to it is capacity reserved for nobody; "
        f"unrouted={unrouted}"
    )
    exceptions = _recorded_exception_ceilings()
    expected = {
        cq: exceptions.get(cq, (0, 0, max(_CEILING_MULTIPLE * quota, _CEILING_FLOOR)))[2]
        for cq, quota in quotas.items()
    }
    wrong = sorted(
        f"{ceilings[cq][0]}: maxRunners={ceilings[cq][1]} quota={quota} " f"expected={expected[cq]}"
        for cq, quota in quotas.items()
        if ceilings[cq][1] != expected[cq]
    )
    assert not wrong, (
        f"each repository's ceiling must be the bounded multiple of its fair share. Too "
        f"HIGH and queued work beyond the bound materializes as pending admission objects "
        f"the host's control plane keeps reconciling, which the section says must wait at "
        f"the forge instead; too LOW — down at the quota — and 'Repositories MAY fairly "
        f"borrow unused capacity' becomes unreachable, because the ceiling IS the "
        f"guaranteed share. Both apply cleanly and neither reports anything; wrong={wrong}"
    )


def _pool_capacity() -> dict[str, int]:
    """Each pool node's `ADMISSION_CAPACITY_C`, keyed by profile name.

    Churn-slot capacity is PER-NODE since the two-node opening (DERIVATION.md
    "The derivation at C = 44 — the two-node pool (2026-09-11)"), while the Kueue
    cohort quota is a single CLUSTER-WIDE number. So the term the fair shares sum
    to is the TOTAL across every node's own profile, not any one node's value.
    """
    capacities: dict[str, int] = {}
    for profile in sorted(_PROFILES_DIR.glob("*.env")):
        declared = _ADMISSION_CAPACITY.search(profile.read_text(encoding="utf-8"))
        assert declared is not None, (
            f"every pool node's admission capacity C must be a value of its committed "
            f"profile — the per-node profile is where the section's host-capacity term "
            f"lives; profile={profile.relative_to(_REPO_ROOT)}"
        )
        capacities[profile.name] = int(declared.group("capacity"))
    return capacities


def test_the_fair_shares_sum_to_the_capacity_the_node_profiles_declare() -> None:
    """The apportionment is exact: the floors add up to the pool's total C across nodes."""
    quotas = _cohort_quotas()
    capacities = _pool_capacity()
    assert capacities, "at least one pool node profile must declare an ADMISSION_CAPACITY_C"
    capacity = sum(capacities.values())
    assert sum(quotas.values()) == capacity, (
        f"the cohort's guaranteed floors must sum to exactly the pool's TOTAL registered "
        f"capacity across every node — the cohort quota is cluster-wide while churn-slot "
        f"capacity is per-node, so it sums to both. Over-subscribed, a floor is not a floor "
        f"— two repositories at their guaranteed share cannot both be admitted; "
        f"under-subscribed, capacity the pool has is unreachable by anyone. Kueue applies "
        f"either without complaint; sum={sum(quotas.values())} capacity={capacity} "
        f"per_node={capacities} quotas={quotas}"
    )


def _assert_fleet_flavor_capacity(
    members: dict[str, dict[str, tuple[str, str | None]]],
    capacity: int,
    reported_flavors: frozenset[str] = frozenset(),
) -> None:
    """Assert the pool capacity against the fleet flavor only, never every flavor."""
    totals = {
        flavor: sum(
            int(quota)
            for flavors in members.values()
            if (entry := flavors.get(flavor)) is not None and (quota := entry[0]).isdecimal()
        )
        for flavor in {
            _FLEET_FLAVOR,
            *reported_flavors,
            *(flavor for flavors in members.values() for flavor in flavors),
        }
    }
    assert totals[_FLEET_FLAVOR] == capacity, (
        f"the `{_FLEET_FLAVOR}` quotas alone must equal the pool capacity; "
        f"members={sorted(members)} flavor_totals={totals} capacity={capacity}"
    )


def test_worker_flavor_members_are_read_but_never_counted_as_fleet_capacity() -> None:
    """Worker quota holders are template-derived, non-borrowing, separate flavor members."""
    members = _cohort_flavor_quotas()
    worker_holders = {
        member: entry
        for member, flavors in members.items()
        for flavor, entry in flavors.items()
        if flavor.startswith("churn-slot-worker-") and entry[0] != "0"
    }
    assert worker_holders == {"livespec-dev-tooling-arm64-cq": (_WORKER_QUOTA_TEMPLATE, "0")}
    _assert_fleet_flavor_capacity(members, sum(_pool_capacity().values()))


def test_worker_flavor_fixture_does_not_inflate_the_fleet_flavor_total() -> None:
    """A moved worker quota fails with its member and both flavor totals named."""
    fleet_member = """kind: ClusterQueue
metadata:
  name: fleet-cq
spec:
  cohortName: fleet-ci-runner-pool
  resourceGroups:
    - coveredResources: [\"ci-runner.io/churn-slot\"]
      flavors:
        - name: churn-slot-flavor
          resources:
            - name: \"ci-runner.io/churn-slot\"
              nominalQuota: 30
"""
    worker_member = """kind: ClusterQueue
metadata:
  name: fixture-worker-cq
spec:
  cohortName: fleet-ci-runner-pool
  resourceGroups:
    - coveredResources: [\"ci-runner.io/churn-slot\"]
      flavors:
        - name: {flavor}
          resources:
            - name: \"ci-runner.io/churn-slot\"
              nominalQuota: 1
              borrowingLimit: 0
"""
    worker_flavor = "churn-slot-worker-arm64-flavor"
    _assert_fleet_flavor_capacity(
        _cohort_flavor_quotas([fleet_member, worker_member.format(flavor=worker_flavor)]),
        30,
        frozenset({worker_flavor}),
    )

    try:
        _assert_fleet_flavor_capacity(
            _cohort_flavor_quotas([fleet_member, worker_member.format(flavor=_FLEET_FLAVOR)]),
            30,
            frozenset({worker_flavor}),
        )
    except AssertionError as error:
        message = str(error)
    else:
        raise AssertionError(
            "moving fixture-worker-cq onto churn-slot-flavor must exceed its capacity"
        )
    assert "fixture-worker-cq" in message
    assert "'churn-slot-flavor': 31" in message
    assert "'churn-slot-worker-arm64-flavor': 0" in message


def test_measured_job_hours_derive_the_committed_fair_shares() -> None:
    """Seven-day pool job-hours are the dated, auditable source of every quota.

    The committed quota VALUES are not asserted here (contracts.md "Config-value
    fast path" forbids a test of a quota key asserting its literal value): a
    re-derivation that moves a queue's quota, with a dated DERIVATION.md section,
    leaves this test passing. The shape is asserted instead: the cohort has
    members, and each member's churn-slot floor is a positive integer.
    """
    quotas = _cohort_quotas()
    assert quotas, "the fleet-ci-runner-pool cohort must have at least one member queue"
    not_positive = {
        name: quota for name, quota in quotas.items() if not (isinstance(quota, int) and quota >= 1)
    }
    assert (
        not not_positive
    ), f"every cohort member needs a positive integer churn-slot floor; got {not_positive}"

    derivation = _DERIVATION.read_text(encoding="utf-8")
    assert "## Measured job-hours re-derivation at C = 44 (2026-10-22)" in derivation
    assert "SUM(duration_ms) / 3,600,000" in derivation
    assert "deducts one from `livespec-orchestrator-beads-fabro` (30 → 29)" in derivation
    assert "## The master-push slice for livespec-dev-tooling (2026-11-03)" in derivation
    assert (
        "## The master-push slice for livespec-orchestrator-beads-fabro (2026-11-12)" in derivation
    )
    assert "## The fabro fork scale set (2026-11-05)" in derivation
    assert "## gamingpc-xubuntu joins: cohort 31 (2026-11-11)" in derivation
    assert "## Per-node CPU budget cut: cohort 30 (2026-11-13)" in derivation
    assert "## Small-queue floor of 2: cohort 30 re-split (2026-11-14)" in derivation
    assert "## Stranded-capacity raise: gmktec 9, cohort 33 (2026-11-16)" in derivation
    assert "## hp 4 -> 3: cohort 32 (2026-11-16)" in derivation
    assert "## gmktec 8: cohort 31 (2026-11-16)" in derivation
    assert "## gamingpc 4: cohort 32 (2026-11-18)" in derivation


def test_master_push_slices_lend_their_floor_and_never_preempt() -> None:
    """Every cohort member lends its whole floor, the master slices included.

    R301 (legacy-coordinator-agent, 2026-11-22, DERIVATION.md "Master lanes lend
    their reserved slots (2026-11-22, R301)"): the 2026-11-03 `lendingLimit: 0`
    reservation idled 4 of 31 slots while pull-request and merge-queue work sat
    gated. The master slices keep their floor and keep every preemption setting
    at Never (the standing NEVER EVICT A HEALTHY RUNNING JOB directive); a master
    workload inside its own nominal is admitted ahead of borrowers on the next
    freed slot, without evicting anything.
    """
    lending = {
        document_name.group("name"): limit.group("limit")
        for document in _documents()
        if (document_name := _NAME.search(document)) is not None
        and (limit := _LENDING_LIMIT.search(document)) is not None
    }
    masters = {"livespec-dev-tooling-master-cq", "livespec-orchestrator-master-cq"}
    assert lending == {}
    for name in masters:
        master = next(
            document
            for document in _documents()
            if (found := _NAME.search(document)) is not None and found.group("name") == name
        )
        for setting in ("reclaimWithinCohort: Never", "policy: Never", "withinClusterQueue: Never"):
            assert setting in master


def test_every_recorded_exception_is_a_derivation_row_that_still_permits_borrowing() -> None:
    """Each exception is a DERIVATION.md row, matches the manifests, and keeps maxRunners > quota.

    The row is where the measurement and the acceptance check live, so an
    exception in this file without one is a number nobody can audit. And an
    exception may move a ceiling off the rule but never down to the share: the
    section requires the ceiling to be "large enough that a repository can
    borrow unused capacity beyond its guaranteed share".
    """
    quotas = _cohort_quotas()
    ceilings = _scale_set_ceilings()
    for cq, (recorded_quota, rule_value, ceiling) in _recorded_exception_ceilings().items():
        assert recorded_quota == quotas[cq], (cq, recorded_quota, quotas[cq])
        assert rule_value == max(_CEILING_MULTIPLE * quotas[cq], _CEILING_FLOOR)
        assert ceiling == ceilings[cq][1], (cq, ceiling, ceilings[cq])
        assert ceiling > quotas[cq], (
            f"{cq}: an exception may waive the rule but not the borrowing clause; "
            f"maxRunners={ceiling} nominalQuota={quotas[cq]}"
        )


def test_no_committed_admission_path_reaches_or_doubles_the_physical_cap() -> None:
    """ "no configuration or recovery path may derive or admit 964 runners"."""
    ceilings = _scale_set_ceilings()
    admissible = sum(ceiling for _, ceiling in ceilings.values())
    assert admissible <= _PHYSICAL_CAP, (
        f"every scale set at its ceiling simultaneously must stay within the physical "
        f"host-wide cap of {_PHYSICAL_CAP} active runners; admissible={admissible}"
    )
    doubling = sorted(
        f"{path.relative_to(_REPO_ROOT)}"
        for path in (*sorted(_KUEUE_DIR.glob("*.yaml")), *sorted(_ARC_DIR.glob("values-*.yaml")))
        if re.search(
            rf"^\s*\w+:\s*{_FORBIDDEN_DOUBLING}\s*$", path.read_text(encoding="utf-8"), re.MULTILINE
        )
    )
    assert not doubling, (
        f"the section forbids any configuration or recovery path DERIVING or admitting "
        f"{_FORBIDDEN_DOUBLING} runners — the doubling of the physical cap that the "
        f"'doubled repository logical ceiling' term invites when it is read as applying "
        f"to the host rather than to a repository; doubling={doubling}"
    )
