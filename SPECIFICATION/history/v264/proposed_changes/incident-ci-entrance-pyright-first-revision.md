---
proposal: incident-ci-entrance-pyright-first.md
decision: accept
revised_at: 2026-11-23T03:21:03Z
author_human: Chad Woolley <thewoolleyman@gmail.com>
author_llm: claude-opus
---

## Decision and Rationale

Accepted as filed for livespec-dev-tooling-xdt4ue: the incident CI entrance completes the locked pyright provisioning serially before it launches any selected member, launches no member on a failed provisioning, writes one line naming it and fails the job, and attempts no provisioning where the lock does not pin pyright. This repays the spec debt of the expedited fix measured on livespec#3199 (two pyright members racing one cold typeshed install). The contracts paragraph is placed after the closing sentence of the trust-boundary paragraph's list ('The test MUST fail when the two definitions differ...'), which belongs to that paragraph-and-list unit, so the sentence is not orphaned from its list; the text is unchanged. The scenario follows the named incident-ci forge read scenario. A spec-first heading-coverage TODO row owed at the integration tier or above is owned by livespec-dev-tooling-xdt4ue. Independent review (sonnet) found no blockers on the exact bytes.

## Resulting Changes

- contracts.md
- scenarios.md
- ../tests/heading-coverage.json

## Ratification Review

ratification_review: auto-spawn
reviewer_model: sonnet
reviewer_identity: sonnet
separate_reviewer: True
read_only: True
reviewed_at: 2026-11-23T03:20:33Z
verdict: NO BLOCKERS
proposal_stem: incident-ci-entrance-pyright-first
content_digest: c4c17935f62e542f06465bd72a53140d4cfd1c5b8da3d15f3f3ebbbcfe3ea68d
