---
topic: ledger-mailbox-seat-channel
author: claude-sonnet-5-5
created_at: 2026-11-21T20:07:35Z
---

## Proposal: A durable ledger mailbox is the default cross-machine seat channel

### Target specification files

- SPECIFICATION/non-functional-requirements.md

### Summary

Add one H2 section, "Ledger mailbox seat channel", stating the mailbox as the default cross-machine seat channel: a record schema in the shared ledger, a send command that fails loudly, a read command that stamps messages read once, a seat hook that injects unread messages at turn boundaries, and an out-of-band urgent poller that alarms and never types.

### Motivation

Plan ledger-mailbox-seat-channel (epic livespec-dev-tooling-4pa43l), successor of remote-control-retirement (livespec-dev-tooling-s63cb5), implements the design in plan/remote-control-retirement/research/002-ledger-mailbox-design.md (livespec-dev-tooling#5201). Remote Control deadlocked fifteen seats on 2026-11-21 ~00:09Z; typing into panes interrupts the maintainer and does not cross hosts. The delivery-timing question is decided as Option 1 (turn boundary plus out-of-band urgent alarm), attested by legacy-coordinator-agent on the maintainer's 2026-11-21 delegation. The three implementation children (livespec-dev-tooling-o767ny, -huv4ew, -f5upsw) cannot be admitted until a ratified heading governs them.

### Proposed Changes

In SPECIFICATION/non-functional-requirements.md add a new H2 section `## Ledger mailbox seat channel` after `## Interactive fleet seat profile`, stating:

- **Record.** One ledger record per message carrying `from`, `to` (a seat name as ListAgents names it), `urgency` (`normal` or `urgent`), `body`, `sent_at`, `read_at` and `read_by`. A message is addressed to a seat, never to a pane or a machine.
- **Send.** `mailbox send --to <seat> --urgency <u> <body>` writes the record through the ledger wrapper, prints the record id, and exits non-zero without printing an id when the ledger refuses the write.
- **Read.** `mailbox read --me <seat>` returns every unread message addressed to that seat, oldest first, and stamps `read_at` and `read_by` on each so a message is delivered once.
- **Hook.** A hook installed in each seat's harness on every dev host runs at turn boundaries, injects the seat's unread messages into its context, exits zero without blocking when the ledger is unreachable, and never writes to a pane, terminal or multiplexer session.
- **Urgent alarm.** A host service running outside any agent session alarms for an `urgent` message unread past a dwell, through the journal, an alarm file and a ledger comment on the coordinator epic, exactly once per message. It never types into a pane and never answers a dialog.
- **No deadlock.** No part of the channel raises a selection dialog; a ledger outage, an absent hook or a stopped poller each degrades only its own leg.
- **Typing remains allowed** for slash commands and pickers; the mailbox is the default for messages, not a ban on pane typing.
