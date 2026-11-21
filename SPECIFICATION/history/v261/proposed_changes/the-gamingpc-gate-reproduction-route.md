---
topic: the-gamingpc-gate-reproduction-route
author: claude-opus-5-5
created_at: 2026-11-13T06:31:07Z
amended_at: 2026-11-21T18:58:00Z
amended_by: gate-job-resources
---

## Proposal: The per-node gate reproduction route is ratified, and its gamingpc and hp pieces are retired

### Target specification files

- SPECIFICATION/contracts.md
- SPECIFICATION/scenarios.md

### Summary

AMENDED 2026-11-21. The first draft (2026-11-13) retired the whole operator reproduction route. That no longer matches the fleet: the route is now a per-node route with live users, and legacy-coordinator-agent held this proposal for that reason. This draft ratifies the route that exists and retires only the two pieces nothing needs.

State that an ordinary gate Job manifest names the `gates-lq` LocalQueue, that the operator reproduction route (`just gate-repro`, which runs `python -m livespec_dev_tooling.gate_repro`) is the ONLY caller that names another LocalQueue, `gates-repro-lq`, and that the `gates-repro-cq` ClusterQueue holds one ResourceFlavor per node it may reproduce on, each pinned to its node by hostname, with quota only on `gmktec-xubuntu` and `poweredge-xubuntu`. The gamingpc and hp flavors are retired: the pool's converge deletes the `gates-repro-gamingpc-flavor` and `gates-repro-hp-flavor` ResourceFlavors idempotently, after the ClusterQueue stops listing them. A scenario states the observable behaviour. Today the spec is silent on the route, so both its existence and the retirement are unratified.

### Motivation

Work item livespec-dev-tooling-caq7uh, a child of plan gate-job-resources (epic livespec-dev-tooling-ukoeah), assertion 6 (stranded capacity). livespec-dev-tooling-pkmxgu added an operator reproduction route so that one diagnosed full-suite gate could run on a lane held at zero (first gamingpc-xubuntu, for livespec-dev-tooling-ddy5xu). ddy5xu is closed and `gates-gamingpc-flavor` admits gates again, so the gamingpc reproduction flavor has no purpose: its quota was zeroed on 2026-11-12 and was armed again only briefly, for the wg4a2x and ybqgri measurements, and disarmed after each (7b9811730, 11ed945ef).

The route itself has since GROWN users and must stay. livespec-dev-tooling-cwrg3v made it per-node (`just gate-repro --node <node>` renders a required hostname nodeSelector, and Kueue assigns only the flavor whose nodeLabels agree). `gates-repro-gmktec-flavor` and `gates-repro-poweredge-flavor` are armed (gmktec one 5 cpu / 8Gi unit, poweredge 10 cpu / 8Gi, per plan gate-job-resources' per-node CPU budget, livespec-dev-tooling-wirn53). The route carries the oaf4vn independent replayer, the wg4a2x ten-Job replay-suite capture and the Jobs rgjkn, qdf4g and dlzmr, and the `expedited-incident-response-flag` plan's wg4a2x capture depends on it. The hp flavor was zeroed on 2026-11-19 after two repro Jobs overcommitted hp-xubuntu beside two factory sandboxes (wirn53); with no seat arming it, it is retired with gamingpc rather than kept as a dead lane.

The converge applies committed files and never prunes, so deleting the two flavors from `cluster-queue-repro-gates.yaml` would leave the two cluster objects in place; the deletion has to be part of the converge so that the retirement is reached through the normal route rather than a hand `kubectl delete`. A ResourceFlavor that a ClusterQueue still lists cannot be deleted, so the converge MUST apply the edited ClusterQueue first. Alignment: the pending proposal gate-placement-and-kueue-admission names `gates-repro-cq` in a parenthetical list of gate ClusterQueues whose admissions are recorded. That clause stays true, because the queue stays; this proposal aligns with it.

### Proposed Changes

In `contracts.md` §"Delegated pre-push gate", add one bullet after **Gate lane headroom**:

- **One ordinary gate queue, one operator reproduction queue.** Every gate Job manifest that `ci-runner/k3s/phase2/gates/render-gate-job.sh` renders MUST name `gates-lq` as its `kueue.x-k8s.io/queue-name` LocalQueue unless the caller passes `--queue`. Exactly two callers pass it: the gate client, for a repository that declares `gate_queue`, passes that declared LocalQueue (this section's *Keys* clause for `gate_queue`), and the operator reproduction route (`just gate-repro`, `python -m livespec_dev_tooling.gate_repro`) passes `gates-repro-lq`. Every other gate Job the gate client submits for a push, a commit or a delegated gate run therefore admits through the `gates-cq` ClusterQueue and its committed lanes. The `gates-repro-cq` ClusterQueue MUST hold one ResourceFlavor per node a reproduction may run on, each selecting its node by hostname, and a flavor whose node is not armed MUST hold zero quota. Quota MUST be held ONLY on `gmktec-xubuntu` and `poweredge-xubuntu`: the `gates-repro-gamingpc-flavor` and `gates-repro-hp-flavor` ResourceFlavors are retired, and the self-hosted pool's converge MUST delete both whenever it runs, after applying the ClusterQueue that no longer lists them, and the delete MUST be idempotent: an object that is already absent MUST NOT fail the converge. A reproduction Job MUST carry a required hostname nodeSelector for the node it names (`just gate-repro --node <node>`), so that it is admitted through that node's flavor and runs only there; the route's `--repro-stack-interval` flag renders the diagnostics container the reproduction owes its evidence from. A lane that has to be withheld from ordinary gates MUST be withheld by its quota in `cluster-queue-gates.yaml`. Arming a reproduction flavor belongs to plan gate-job-resources' per-node CPU budget (a reproduction gate is a second claim on a node whose budget does not count it) and is a separate reviewed change that reverts by restoring zero. This bullet binds every gate Job the gate client submits, so it covers §"Delegated commit-time replay test runs", §"Delegated pre-commit aggregate" and §"Delegated gate-runner runs" as well as this section. It is spec-first: as of its ratification the `gates-repro-gamingpc-flavor` and `gates-repro-hp-flavor` objects exist on the cluster; work item livespec-dev-tooling-nkocp5 (which replaces the closed livespec-dev-tooling-caq7uh) owns their retirement.

In `scenarios.md`, add:

## Scenario: an ordinary gate Job renders onto the one gate queue, and the per-node reproduction route admits only through an armed node flavor

```gherkin
Given the committed gate Job renderer ci-runner/k3s/phase2/gates/render-gate-job.sh and the committed gates-repro-cq ClusterQueue
When the renderer renders a gate Job manifest from valid arguments and no --queue
Then the manifest's kueue.x-k8s.io/queue-name label MUST be gates-lq.
And the renderer invoked with --queue gates-repro-lq and --node gmktec-xubuntu MUST render a Job whose queue-name label is gates-repro-lq and whose nodeSelector requires kubernetes.io/hostname gmktec-xubuntu.
And the gates-repro-cq ClusterQueue MUST list a ResourceFlavor for gmktec-xubuntu and one for poweredge-xubuntu, and MUST list none for gamingpc-xubuntu or hp-xubuntu.
And a converge run MUST leave neither the gates-repro-gamingpc-flavor nor the gates-repro-hp-flavor ResourceFlavor on the cluster, and a second run MUST NOT fail on their absence.
```

The revise that accepts this proposal MUST add the scenario's heading to `tests/heading-coverage.json` in the same commit, as a spec-first `test: "TODO"` row whose `work_item` is livespec-dev-tooling-nkocp5 and whose reason names the integration tier, and MUST register it in the debt register.
