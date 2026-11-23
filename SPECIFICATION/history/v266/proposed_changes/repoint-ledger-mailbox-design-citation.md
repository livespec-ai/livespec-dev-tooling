---
topic: repoint-ledger-mailbox-design-citation
author: claude-sonnet-5-5
created_at: 2026-11-23T08:08:35Z
---

## Proposal: Repoint the ledger-mailbox design citation to the archived plan path

### Target specification files

- SPECIFICATION/non-functional-requirements.md

### Summary

The durable-ledger-mailbox paragraph cites plan/remote-control-retirement/research/002-ledger-mailbox-design.md; the plan is archived, so the citation moves to plan/archive/remote-control-retirement/research/002-ledger-mailbox-design.md.

### Motivation

archive_thread refuses to archive a plan while any file outside plan/ cites its path. The citation is a pointer to a design note; no behaviour changes.

### Proposed Changes

In non-functional-requirements.md, in the paragraph beginning 'A durable ledger mailbox is the default channel', replace 'plan/remote-control-retirement/research/002-ledger-mailbox-design.md' with 'plan/archive/remote-control-retirement/research/002-ledger-mailbox-design.md'. No other change.
