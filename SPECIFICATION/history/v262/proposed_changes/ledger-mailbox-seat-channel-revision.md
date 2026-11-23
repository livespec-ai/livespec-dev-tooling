---
proposal: ledger-mailbox-seat-channel.md
decision: modify
revised_at: 2026-11-21T22:25:55Z
author_human: Chad Woolley <thewoolleyman@gmail.com>
author_llm: claude-sonnet-5-5
---

## Decision and Rationale

Re-cut as v262 after livespec-dev-tooling#5231 took v261. The ratified text is byte-identical to the five-round-reviewed text; a fresh independent reviewer re-attested the rebased bytes. Implements the delegated Option 1 delivery-timing decision of plan remote-control-retirement.

## Modifications

Adds a scenario, a 120 s configurable dwell, the Relation-to-SendMessage clause with durability precedence, and embeds the final text in the proposal.

## Resulting Changes

- non-functional-requirements.md
- scenarios.md

## Ratification Review

ratification_review: auto-spawn
reviewer_model: sonnet
reviewer_identity: sonnet
separate_reviewer: True
read_only: True
reviewed_at: 2026-11-21T22:24:52Z
verdict: NO BLOCKERS
proposal_stem: ledger-mailbox-seat-channel
content_digest: 2876aeb1bce3cb716124d8a48ec5c8a9e11127721c66a83f207f8f9bc5087ed7
