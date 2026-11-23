---
topic: the-claude-scratch-mover-never
author: claude-sonnet-5-5
created_at: 2026-11-23T07:55:00Z
---

## Proposal: The dev host's Claude scratch mover is a stated component of the disk retention, with its safety and memory behaviour

### Target specification files

- SPECIFICATION/non-functional-requirements.md

### Summary

Add one paragraph, "Claude scratch mover", to the section "## Dev host disk retention". It states the behaviour of the mover that role `dev_host_memory_bounds` installs: a name clash on put-back or restore, a partial destination, a standing destination-exists state, the project directory's mode, and the pass's memory bound.

### Motivation

Work items livespec-dev-tooling-7axaqn and livespec-dev-tooling-axmeds were recorded at the spec-change tier on 2026-11-14 because the ratified section says nothing about the Claude scratch mover (`claude_scratch_mover.py`, `claude_scratch_mover_scan.py`). Their linked topics (this one, and a-claude-scratch-mover-pass) were never filed. The factory's Definition-of-Done gate therefore refuses 7axaqn at its coherence check: no heading's section states put-back, restore-blocked, partial-destination cleanup, the standing destination-exists state or project-directory mode correction. This proposal supplies the clause; axmeds' memory bound is stated in the same paragraph so one ratification covers both items. It belongs to plan dev-host-disk-retention and adds no new behaviour: it states what the merged mover already does (axmeds) and what 7axaqn's Definition of Done requires.

### Proposed Changes

In SPECIFICATION/non-functional-requirements.md, section "## Dev host disk retention", add this paragraph immediately before the paragraph that begins "Cargo build targets are deliberately outside this section":

**Claude scratch mover.** The role that bounds the dev host's memory, `dev_host_memory_bounds`, installs a timer-run mover that moves a dead Claude Code session's scratch directory off the `/tmp` tmpfs onto disk and never deletes one. The mover MUST keep a session that any running process references, and MUST keep every session when no running process's environment could be read. A pass MUST read the running processes one at a time and MUST hold in memory, across processes, only the set of session ids that some process names; a completed pass's `MemoryPeak`, read with `systemctl show` on the dev host, MUST be under 256M. When the mover puts a staged session back, or restores a staging directory a crashed pass left, and the session's original name already exists, it MUST leave both directories in place, log a `restore-blocked` event naming both paths, and neither replace nor delete either. After a failed copy that put the session back under the RAM root, it MUST remove the partial destination that copy left, so that a later pass can move the session, and it MUST NOT remove a partial destination while the session is not back under the RAM root. A session whose destination already exists MUST be reported as one logged standing state, and a pass in which that is the only finding MUST exit 0. A move into an on-disk project directory that already exists and is owned by the user running the mover MUST leave that directory with the source project directory's mode.

### Revise-time co-edits

None. The paragraph adds no `## ` heading, so tests/heading-coverage.json is unchanged.
