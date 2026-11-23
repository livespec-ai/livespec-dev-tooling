---
proposal: the-dev-host-capacity-alert.md
decision: accept
revised_at: 2026-11-23T15:15:52Z
author_human: Chad Woolley <thewoolleyman@gmail.com>
author_llm: claude:dev-host-disk-retention
---

## Decision and Rationale

Ratifies the authenticated, rate-limit-aware capacity alert (bearer token from a root-only file, never in a unit file or log; anonymous fallback with a log line; HTTP 429 logged distinctly and not counted as sent) so livespec-dev-tooling-kvmjvm has a governing clause. Per legacy-coordinator-agent R301 the token-secrecy rule is a security guarantee that belongs in the spec.

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
proposal_stem: the-dev-host-capacity-alert
content_digest: f035c062e2925a87c2de3d2fa417e49e67fc2d57bd52912506fa5d2a8e760776
