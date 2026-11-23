## The maintainer's statement of what done means

IMPLEMENT the durable ledger mailbox designed in livespec-dev-tooling#5201 (plan/remote-control-retirement/research/002-ledger-mailbox-design.md). It is the default cross-machine seat channel: a seat reads its unread messages through a hook at turn boundaries, and no component types into a pane. Delivery timing is DECIDED: Option 1, delivery at the receiving session's turn boundary plus an out-of-band alarm for urgent messages (attested by legacy-coordinator-agent on the maintainer's 2026-11-21 ~19:4xZ delegation).

## Definition of Done assertions derived from that statement

- A seat sends a message to another seat by name with the mailbox command, which writes one record to the shared ledger, prints its id, and exits non-zero without printing an id when the ledger refuses the write.
- A seat on a different host than the sender reads that message through the mailbox read command, which returns every unread message addressed to the seat and stamps each one read exactly once.
- A hook installed in a seat's harness on every dev host injects the seat's unread mailbox messages into its context at its next turn boundary, with no text typed into any pane.
- A host service running outside any agent session raises an alarm through the journal, the alarm file and a ledger comment on the coordinator epic for an urgent message unread past its dwell, and it never types into a pane or answers a dialog.
- No mailbox component can raise a selection dialog, and a ledger outage, an absent hook or a stopped poller each leaves the other legs delivering rather than leaving a seat waiting.

# Charter: ledger mailbox seat channel

Plan ledger-mailbox-seat-channel. Successor of plan remote-control-retirement (epic livespec-dev-tooling-s63cb5); that plan's completeness review s63cb5-completeness-review-2 records the deferral to this one.
Created 2026-11-21 ~20:3xZ on the instruction of legacy-coordinator-agent. The Definition of Done assertions are SESSION-DERIVED, not maintainer-confirmed (unattended creation).

## Scope

Implement the design in plan/remote-control-retirement/research/002-ledger-mailbox-design.md (livespec-dev-tooling#5201; design item livespec-dev-tooling-laor2c, closed). Three follow-ups named there:

1. The `mailbox` command and record schema in the ledger.
2. The seat read hook and its install on every dev host.
3. The urgent poller as a host role beside seat_dialog_watchdog (ansible/roles/seat_dialog_watchdog is the shape to copy).

## Decided

Delivery timing: Option 1 (next turn boundary plus an out-of-band alarm for urgent messages). Option B (typed nudge) is NOT built. The PANE-TYPING-ALLOWED ruling is untouched: slash commands and pickers still need typing.

## Out of scope

Typing a nudge into a pane; replacing Remote Control for slash commands; changing seat_dialog_watchdog behaviour.
