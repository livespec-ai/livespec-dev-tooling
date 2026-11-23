---
proposal: container-reclaim-image-leg-keys-by-tag-series-and-last-tag-time.md
decision: accept
revised_at: 2026-11-23T15:15:52Z
author_human: Chad Woolley <thewoolleyman@gmail.com>
author_llm: claude:dev-host-disk-retention
---

## Decision and Rationale

Ratifies role container_reclaim's image leg (unused, aged from LastTagTime else Created, not the newest image of its repository and tag series, each removal logged) so livespec-dev-tooling-3k7fga has a governing clause on every host the role is applied to.

## Resulting Changes

- non-functional-requirements.md

## Ratification Review

ratification_review: auto-spawn
reviewer_model: sonnet
reviewer_identity: sonnet
separate_reviewer: True
read_only: True
reviewed_at: 2026-11-23T15:15:50Z
verdict: NO BLOCKERS
proposal_stem: container-reclaim-image-leg-keys-by-tag-series-and-last-tag-time
content_digest: ee99a35e9da41e3133d4cecebe253313a008eb62802490d72b5650add752ee1a
