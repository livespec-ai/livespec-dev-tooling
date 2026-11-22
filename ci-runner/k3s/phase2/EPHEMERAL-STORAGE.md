# Ephemeral-storage requests of the gate and factory pod classes

Work item livespec-dev-tooling-tsde55 (plan gate-job-resources, assertion 7).
On 2026-11-19 poweredge-xubuntu reached DiskPressure and the kubelet evicted
the git-gates pods, because no pod requested ephemeral-storage and the
scheduler could not see the disk. A request lets a full node refuse a new pod
instead.

## Rule

request = measured per-pod peak x 1.25, rounded up (gates to 0.5 GiB, factory
sandboxes to 1 GiB). A REQUEST only, never a limit: a limit would make the
kubelet evict the pod for disk use, which is the failure this removes.

## Measurement

Source: kubelet `stats/summary` `pods[].ephemeral-storage.usedBytes`, read with
`kubectl get --raw /api/v1/nodes/<node>/proxy/stats/summary`, 2026-11-21
22:41Z, every Ready node. gamingpc-xubuntu was NotReady and unread.

| class | pods read | per-pod usage (GiB) | peak | request |
|---|---|---|---|---|
| gates (`gates` ns) | 4 | 0.01, 1.04, 1.59, 1.62 | 1.62 | 2560Mi |
| factory sandbox (`factory` ns) | 11 | 0.00, 0.00, 0.00, 1.36, 1.48, 1.48, 1.58, 1.68, 1.68, 1.73, 2.12 | 2.12 | 3Gi |

Both are point-in-time reads of running pods, so a pod still growing is read
below its final size; the 1.25 factor is the margin. Re-measure from a window
of finished pods before lowering either value.

## Where the values live

- Gates: `gates/render-gate-job.sh` default `ephemeral_storage` (flag
  `--ephemeral-storage`), rendered into the gate container's requests by
  `gates/gate-job-template.yaml`.
- Factory sandboxes: the `factory-ephemeral-storage` LimitRange in
  `factory/factory-namespace.yaml` (the sandbox driver sets no request).
  The mi-homelab namespace is out of scope.
