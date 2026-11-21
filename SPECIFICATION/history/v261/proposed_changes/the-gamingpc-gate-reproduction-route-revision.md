---
proposal: the-gamingpc-gate-reproduction-route.md
decision: accept
revised_at: 2026-11-21T20:05:14Z
author_human: Chad Woolley <thewoolleyman@gmail.com>
author_llm: claude-sonnet-5-5
---

## Decision and Rationale

Accept as amended (livespec-dev-tooling#5224 and #5226): the per-node operator gate reproduction route is ratified (gates-repro-cq with gmktec and poweredge flavors, gate-repro, --node, --repro-stack-interval, the gate_queue caller of --queue) and only the gamingpc and hp flavors are retired. Decider: legacy-coordinator-agent under ruling R301; its pre-answered ACCEPT and its 2026-11-21 ~19:0xZ confirmation that the ACCEPT covers the re-amended bytes (a second chore(spec) PR changing only the gate_queue caller and the nkocp5 owner) are the decider evidence. A first independent review returned two blockers (the bullet contradicted the gate_queue clauses at contracts.md 599/602, and the TODO owner caq7uh is closed); both were fixed in the proposal, and a second independent review of the exact final bytes returned NO BLOCKERS.

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
reviewed_at: 2026-11-21T20:04:38Z
verdict: NO BLOCKERS
proposal_stem: the-gamingpc-gate-reproduction-route
content_digest: f782ca00e7ca1336680d5f5380daa2594b2bf73fcc1267310e11381fafc128de
