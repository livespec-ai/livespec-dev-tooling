---
topic: red-leg-refuses-fixture-order-import-error
author: claude-opus-5-5
created_at: 2026-11-22T15:16:24Z
---

## Proposal: The Red leg refuses a pytest exit-2 Red whose ModuleNotFoundError names a module that exists in the staged tree

### Target specification files

- SPECIFICATION/non-functional-requirements.md
- SPECIFICATION/scenarios.md

### Summary

PARKED. Narrow the red_green_replay Red leg so a Red whose pytest run exits 2 with a ModuleNotFoundError naming a module that EXISTS in the staged tree (a fixture-order or sys.path-order import error, not missing behaviour) is refused instead of recorded as a Red. A ModuleNotFoundError naming a module that does NOT exist in the staged tree (the not-yet-written module of the new-module path) keeps counting as a Red. The proposal also resolves the conflict between the fleet agent-instruction core and the hook's own protocol text about whether an ImportError or collection error counts as a Red. Parked by throughput-plans-coordinator's ruling 2026-11-22: ratify and build only if a SECOND false-Red instance of this shape is measured; first instance livespec-driver-codex-5lwqdt / emxmkn.

### Motivation

Measured FALSE RED, first instance: work item livespec-driver-codex-5lwqdt, Fabro run 01M819KQBSEQ. Its staged Red test, tests/dev-tooling/test_codex_hook_cache_observe.py, could not import when run alone: line 22 imports codex_hook_cache_all before line 26 imports the fixtures module that puts dev-tooling/ on sys.path. pytest exited 2 with ModuleNotFoundError for a module that exists on disk, and the Red leg recorded TDD-Red-* trailers for it. The repro ran in the identical image (gate Job gate-livespec-driver-codex-lgwkj): rc=2 when the file runs alone, 35 passed once the fixtures module is imported first. The cause was fixed in that repository by livespec-driver-codex#1155 (dae4fb4, a conftest), and its root-fix item livespec-driver-codex-emxmkn is done. The gate side is unchanged: `_handle_red_mode` in livespec_dev_tooling/checks/_red_green_replay_modes.py refuses a Red only when `replay.returncode == 0`, so pytest exits 1, 2, 4 and 5 all record a Red, and a Red that proves only that a test file cannot import itself passes as proof of unimplemented behaviour.

The written contract conflicts with itself. The fleet agent-instruction core, shipped from livespec's copier template livespec/templates/orchestrator-plugin/AGENTS.md (governed by livespec contracts.md §"Fleet agent-instruction core") and rendered into every member's AGENTS.md (for example livespec-dev-tooling/AGENTS.md and livespec-orchestrator-beads-fabro/AGENTS.md), says in §"Red-Green-Replay commit protocol" step 1: "The hook runs pytest on the staged tree; the staged test MUST fail on pytest (non-zero exit). An `ImportError` or a collection error counts as a failure to the hook, BUT you SHOULD prefer a genuine assertion failure so Red proves the behavior is actually unimplemented rather than merely unimportable", and in §"New-module stub technique (avoiding false reds)": "The hook accepts that as a failing Red, but it does not prove the behavior is unimplemented". The hook's own protocol text, `RED_GREEN_REPLAY_PROTOCOL` in livespec-dev-tooling/livespec_dev_tooling/checks/_red_green_replay_protocol.py, emitted on every rejection, says: "The hook runs pytest on the staged tree; the new test MUST fail meaningfully (an assertion failure, NOT an ImportError / collection error)." livespec's SPECIFICATION/non-functional-requirements.md §"Test-Driven Development discipline" sides with the protocol text as contributor discipline ("Unhelpful Reds (`ImportError`, `ModuleNotFoundError`, `NameError`, `TypeError` on call shape) MUST be fixed before proceeding to Green."), and this repository's §"Test-Driven Development discipline" binds this library to that same cycle. One of the two hook statements is wrong. Against the gate as shipped, the stale one is the protocol text: it describes a refusal the gate never makes, while the agent-instruction core describes the shipped behaviour accurately. Under the narrower rule proposed here neither is exact, so both are rewritten to the one rule below.

### Proposed Changes

PARK NOTE: Parked by throughput-plans-coordinator's ruling 2026-11-22: ratify and build only if a SECOND false-Red instance of this shape is measured; first instance livespec-driver-codex-5lwqdt / emxmkn. A revise pass MUST NOT accept this proposal before a second instance is measured and recorded in this file's Motivation.

Chosen option: the NARROWER refusal. The wider option, refusing every exit-2 Red or every ImportError/collection-error Red, is rejected: it would refuse the Red of a not-yet-written module, which is the new-module path the fleet agent-instruction core relies on, and it would force a stub on every first-file Red.

1. In SPECIFICATION/non-functional-requirements.md §"Test-Driven Development discipline", add this bullet directly after the bullet beginning "The Red → Green commit pair is enforced by the `red_green_replay` check":

- **A Red that cannot import an existing module is not a Red.** When the `red_green_replay` Red leg's pytest run of the staged test file exits `2` and its output reports a `ModuleNotFoundError` for a dotted module name `a.b.c`, the leg MUST decide whether that module exists in the staged tree. The module exists when the staged tree holds a file whose path ends with `a/b/c.py` or `a/b/c/__init__.py`. When it exists, the failure is an import-order or `sys.path`-order defect of the test file, not missing behaviour, and the leg MUST refuse the commit with a `check_id` distinct from `red-green-replay-test-passed-at-red`, name the test file, the module and the staged path that provides it, tell the committer to make the test file import on its own (for example through a `conftest.py`), and MUST NOT record any `TDD-Red-*` trailer. When no staged path provides the module, the leg MUST keep recording the Red as today, so a test of a not-yet-written module still Reds. Every other non-zero exit keeps its current treatment. The rule binds the Red leg's run in either venue, local or a delegated gate Job, because §"Delegated commit-time replay test runs" keeps the judgement on the committing host. Fleet scope: the shared `red_green_replay` check, so every consuming repository whose commit-msg hook runs it.

2. In SPECIFICATION/scenarios.md, add:

## Scenario: a Red whose test cannot import a module present in the staged tree is refused

Given a test-only commit that stages one test file

And pytest run on that file alone exits 2 with a ModuleNotFoundError for a module the staged tree provides at a `.py` path

When the commit-msg `red_green_replay` check runs its Red leg

Then it MUST refuse the commit with an event naming the test file, the module and the staged path that provides it

And it MUST NOT record any TDD-Red-* trailer

## Scenario: a Red whose test imports a not-yet-written module is still recorded

Given a test-only commit that stages one test file

And pytest run on that file alone exits 2 with a ModuleNotFoundError for a module no staged path provides

When the commit-msg `red_green_replay` check runs its Red leg

Then it MUST record the TDD-Red-* trailers as for any failing Red

with the matching `tests/heading-coverage.json` entries added in the same revise (`test` MAY be "TODO" with a reason naming the owning work item).

3. Resolve the stated conflict to this one rule in both places. (a) In livespec-dev-tooling, change `RED_GREEN_REPLAY_PROTOCOL` in livespec_dev_tooling/checks/_red_green_replay_protocol.py from "the new test MUST fail meaningfully (an assertion failure, NOT an ImportError / collection error)" to "the new test MUST fail; prefer an assertion failure. A ModuleNotFoundError for a module that exists in the staged tree is refused, because it shows the test file cannot import itself; a ModuleNotFoundError for a module not yet written still counts as a Red". This is the stale statement against the shipped gate. (b) The fleet agent-instruction core is governed by livespec's contracts.md §"Fleet agent-instruction core" and ships from livespec/templates/orchestrator-plugin/AGENTS.md, outside this repository's spec. On ratification of this proposal, file one companion work item in livespec to replace "An `ImportError` or a collection error counts as a failure to the hook" there with "An `ImportError` or a collection error for a module not yet written counts as a failure to the hook; a `ModuleNotFoundError` for a module that already exists in the staged tree is refused", which then reaches every member through the copier template.

Residual, recorded at filing: exits 4 (usage error) and 5 (no tests collected) also record a Red today and are not changed by this proposal; a collection error other than ModuleNotFoundError (for example a SyntaxError) is not changed either.
