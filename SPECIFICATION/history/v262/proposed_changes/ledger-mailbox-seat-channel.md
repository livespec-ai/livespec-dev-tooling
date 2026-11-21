---
topic: ledger-mailbox-seat-channel
author: claude-sonnet-5-5
created_at: 2026-11-21T20:07:35Z
---

## Proposal: A durable ledger mailbox is the default channel for a durable seat-addressed message

### Target specification files

- SPECIFICATION/non-functional-requirements.md
- SPECIFICATION/scenarios.md

### Summary

Add one H2 section, "Ledger mailbox seat channel", stating the mailbox as the default channel for a durable seat-addressed message: a record schema in the shared ledger, a send command that fails loudly, a read command that stamps messages read once, a seat hook that injects unread messages at turn boundaries, and an out-of-band urgent poller that alarms and never types.

### Motivation

Plan ledger-mailbox-seat-channel (epic livespec-dev-tooling-4pa43l), successor of remote-control-retirement (livespec-dev-tooling-s63cb5), implements the design in plan/remote-control-retirement/research/002-ledger-mailbox-design.md (livespec-dev-tooling#5201). Remote Control deadlocked fifteen seats on 2026-11-21 ~00:09Z; typing into panes interrupts the maintainer and does not cross hosts. The delivery-timing question is decided as Option 1 (turn boundary plus out-of-band urgent alarm), attested by legacy-coordinator-agent on the maintainer's 2026-11-21 delegation. The three implementation children (livespec-dev-tooling-o767ny, -huv4ew, -f5upsw) cannot be admitted until a ratified heading governs them.

### Proposed Changes

In SPECIFICATION/non-functional-requirements.md add this new H2 section immediately before `## Runner-pool node rebuild recipe`:

````markdown
## Ledger mailbox seat channel

A durable ledger mailbox is the default channel for a seat-addressed message that must be durable: it survives a relaunch of the recipient and is delivered when the recipient is not a live session that `SendMessage` can reach. It is a table of messages in the shared beads/Dolt ledger the fleet already depends on, and nothing in it types into a pane or raises a dialog. Plan ledger-mailbox-seat-channel (livespec-dev-tooling-4pa43l) implements it, from the design recorded in plan/remote-control-retirement/research/002-ledger-mailbox-design.md.

- **Record.** One ledger record per message, carrying `from`, `to`, `urgency` (`normal` or `urgent`), `body`, `sent_at`, `read_at` and `read_by`. `to` is a seat name, the name the session was given with `/rename`, which is how a seat is addressed to `SendMessage`, never a pane or a machine, so a message survives a relaunch and crosses hosts.
- **Send.** `mailbox send --to <seat> --urgency <u> <body>` writes the record through the ledger credential wrapper and prints the record id. It exits non-zero and prints no record id when the ledger refuses the write, so a sender never believes an undelivered message was sent.
- **Read.** `mailbox read --me <seat>` returns every unread message addressed to that seat, oldest first, and stamps `read_at` and `read_by` on each so a message is delivered once. It never returns a message addressed to another seat.
- **Hook.** A hook installed in each seat's harness on every dev host runs at turn boundaries, injects the seat's unread messages into its context with sender and urgency, injects nothing when there are none, exits zero without blocking when the ledger is unreachable, and never writes to a pane, a terminal or a multiplexer session.
- **Urgent alarm.** A host service running outside any agent session raises an alarm for an `urgent` message unread past its dwell, through the journal, an alarm file and a ledger comment on the coordinator epic, once per message. The dwell is one committed, configurable constant whose default is 120 seconds, and the alarm fires only after it has elapsed. It never types into a pane and never answers a dialog.
- **No deadlock.** No part of the channel raises a selection dialog. A ledger outage, an absent hook or a stopped poller each degrades only its own leg.
- **Relation to the SendMessage clause.** This section complements, and does not amend, the clause "Seats prefer SendMessage; pane typing stays allowed." of §"Interactive fleet seat profile". Where the message must be durable, or the recipient is not a live session that `SendMessage` can reach, the mailbox is the default, and durability takes precedence: a durable message to a reachable seat goes through the mailbox, and `SendMessage` MAY be added. Where the message need not be durable and the recipient is a live session that `SendMessage` can reach, on any host, the `SendMessage` SHOULD in that clause governs and the mailbox is optional. The host never decides which rule applies. The Remote Control managed-policy bullet of that clause is outside what this section decides.
- **Typing stays available.** Slash commands and pickers still need a typed key, and pane typing stays available exactly as that clause requires: the mailbox is the default for messages, not a ban on typing into a pane.
````

In SPECIFICATION/scenarios.md add this scenario immediately before `## Scenario: a memory file on an agent-seat host becomes one migration item in its owning repository`:

````markdown
## Scenario: a seat reads a message another seat sent it through the ledger mailbox without any pane typing

Given two seats on different hosts that share the ledger, and a recipient seat with an installed mailbox read hook

When the sender runs `mailbox send --to <recipient> --urgency normal <body>`

Then the command prints a record id and the ledger holds one record addressed to the recipient

And at the recipient's next turn boundary the hook injects that message into its context and stamps `read_at` and `read_by`

And no text is typed into any pane, and a second read returns no message

And when a message sent with `--urgency urgent` is still unread past the dwell, the poller writes a journal line, an alarm file and a ledger comment on the coordinator epic, once, and types nothing

And when the sender runs the command while the ledger refuses writes, it exits non-zero and prints no record id
````
