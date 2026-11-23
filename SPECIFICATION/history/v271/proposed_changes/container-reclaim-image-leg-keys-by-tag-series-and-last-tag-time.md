---
topic: container-reclaim-image-leg-keys-by-tag-series-and-last-tag-time
author: claude-sonnet-5-5
created_at: 2026-11-23T14:40:00Z
---

## Proposal: Role container_reclaim's image leg keeps each tag series' newest image and measures an image's age from when it was last tagged on the host

### Target specification files

- SPECIFICATION/non-functional-requirements.md

### Summary

Add one paragraph, "Container image reclaim", to the section "## Dev host disk retention". It states which docker images the role `container_reclaim` removes on every host it is applied to: an image no container uses, whose age (from its last tagging on the host, or its creation when it was never tagged) is above the role's idle-hours variable, and which is not the newest image of its repository and tag series. It also states how a tag series is read from a tag.

### Motivation

Work item livespec-dev-tooling-3k7fga (plan dev-host-disk-retention, livespec-dev-tooling-qgwxo4) is recorded at the spec-change tier: no ratified clause governs role `container_reclaim`'s image leg, which already removes unused images older than 72 hours, hourly, on `sandbox_hosts`, `dev_hosts` and `former_sandbox_hosts`. legacy-coordinator-agent's grade of livespec-dev-tooling#4688 (2026-11-14) named two safety points that belong on a clause, and this proposal states them:

- One repository, `ghcr.io/thewoolleyman/livespec-fabro-sandbox`, carries several tag series (python-v..., python-rust-v..., python-rust-fuzz-v..., and the -agent variants). A repository-wide "newest image" rule would delete every series' current image except one, once aged.
- Docker's `Created` is the image's build time, so an image pulled today on a rollback already reads as old. The time the image was last tagged on the host is the right clock.

The clause lives in "## Dev host disk retention" because that section is where the dev host's reclaim of docker images is already stated (its first reclaim bullet removes dangling images and keeps tagged and in-use ones). On 2026-11-14 vmi3006760 held 27.09 G of unused sandbox images, all 21 hours to 2 days old.

### Proposed Changes

In `SPECIFICATION/non-functional-requirements.md`, section "## Dev host disk retention", add this paragraph immediately before the paragraph that begins "Cargo build targets are deliberately outside this section":

**Container image reclaim.** On every host to which the `container_reclaim` role is applied, its image leg MUST remove an image only when all of these hold: no container, running or stopped, uses it; its age is above the role's idle-hours variable, `container_reclaim_image_idle_hours`; and it is not the most recently created image of its repository and tag series. An image's age is the time since it was last tagged on the host (`Metadata.LastTagTime`), or since its `Created` time when it was never tagged. A tag series is a tag with any trailing `-v<MAJOR>.<MINOR>.<PATCH>` removed, so that images of one repository under different series each keep their own newest image. The leg MUST log each image it removes by repository, tag and id.

### Revise-time co-edits

None. The paragraph adds no `## ` heading, so tests/heading-coverage.json is unchanged.
