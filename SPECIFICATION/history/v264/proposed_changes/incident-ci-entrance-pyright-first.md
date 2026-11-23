---
topic: incident-ci-entrance-pyright-first
author: claude-sonnet-5-5
created_at: 2026-11-23T02:07:56Z
---

## Proposal: The incident CI entrance provisions locked pyright serially before it launches any member and names a provisioning failure

### Target specification files

- SPECIFICATION/contracts.md
- SPECIFICATION/scenarios.md

### Summary

State, under Expedited incident execution, that the incident CI entrance completes the locked pyright provisioning before it fans out its selected members, launches no member earlier, fails the job naming the provisioning when it fails, and attempts no provisioning where the lock does not pin pyright. One scenario states it. This is the behaviour livespec-dev-tooling-xdt4ue implements.

### Motivation

Measured 2026-11-13 on livespec#3199 (CI run 43431280787 attempt 2, job incident-ci 131908183610): the entrance ran 72 selected members in parallel and check-no-shadow-ledger-body-typechecks type-checked against a half-written typeshed because two pyright-invoking members started together on a cold cache, while the normal aggregate runs _pyright_warmup.warm_locked_pyright before it fans out. The ratified text states no such ordering, so the fix item xdt4ue repays a spec debt (incident-specific spec debt may be deferred only until that incident's repayment, per the plan). This proposal states the behaviour; the repayment implements and tests it.

### Proposed Changes

In contracts.md section "Expedited incident execution", insert this paragraph directly after the paragraph that begins "The entrance sits on the other side of the trust boundary" and its list (before the next paragraph):

> **The incident CI entrance provisions locked pyright before it launches a member.** When the repository's lock pins pyright, the incident CI entrance MUST complete the locked pyright provisioning (the serial first-run install the normal dispatcher performs before it fans out) before it launches ANY selected member, so that two selected members which both invoke pyright never race one cold install. It MUST launch no member earlier than that completion. When the provisioning fails, the entrance MUST launch no member, MUST write one line naming the provisioning and its failure, and MUST fail the job, never report the members as passed or deferred. When the repository's lock does not pin pyright, the entrance MUST launch its members without attempting any pyright provisioning.

In scenarios.md, add this scenario directly after "## Scenario: an incident-ci forge read retries an unusable answer and an unreadable pull-request body fails the selection by name":

## Scenario: the incident CI entrance provisions locked pyright before it launches any member

```gherkin
Given an incident CI plan that selects two members which both invoke pyright, in a repository whose lock pins pyright, on a runner whose pyright cache is cold
When the incident CI entrance executes the plan
Then the entrance MUST complete the locked pyright provisioning exactly once before it launches either member
And it MUST launch neither member until that provisioning has completed
And when the provisioning fails, the entrance MUST launch no member, MUST print one line naming the provisioning and its failure, and MUST fail the job
And in a repository whose lock does not pin pyright, the entrance MUST launch its members without attempting any pyright provisioning.
```

In tests/heading-coverage.json add a spec-first row for the new scenario heading with test "TODO", a reason naming the tier (a real test at the integration tier or above is owed for this heading) and a work_item key livespec-dev-tooling-xdt4ue, then run just generate-heading-coverage-debt-register and stage tests/heading-coverage-debt.json.
