---
proposal: the-claude-scratch-mover-never.md
decision: modify
revised_at: 2026-11-23T09:42:05Z
author_human: Chad Woolley <thewoolleyman@gmail.com>
author_llm: claude:dev-host-disk-retention
---

## Decision and Rationale

Ratifies the Claude scratch mover as a stated component of Dev host disk retention so work items livespec-dev-tooling-7axaqn and livespec-dev-tooling-axmeds have a governing clause. Modified after the independent review: the project-directory rule now covers an existing real directory (not a symlink) and sets the source's owner and mode, because the mover runs as root.

## Modifications

Project-directory sentence: 'already exists as a real directory, not a symlink, MUST leave that directory with the source project directory's owner and mode' replaces 'owned by the user running the mover ... mode'. 'never deletes one' becomes 'never deletes a session's only copy'. The MemoryPeak bound now names the mover's service unit.

## Resulting Changes

- non-functional-requirements.md

## Ratification Review

ratification_review: auto-spawn
reviewer_model: sonnet
reviewer_identity: sonnet
separate_reviewer: True
read_only: True
reviewed_at: 2026-11-23T09:42:02Z
verdict: NO BLOCKERS
proposal_stem: the-claude-scratch-mover-never
content_digest: dd993bc239695fac41709753a913238bc40355ce25b0a5e0fabc0319bda5ee8f
