---
topic: caam-delivery-push-role-installs-the-pinned-binary
author: bqnzcm-plan-seat
created_at: 2026-11-22T21:04:13Z
---

## Proposal: caam-delivery-push-role-installs-the-pinned-binary

### Target specification files

- SPECIFICATION/non-functional-requirements.md

### Summary

State the caam_delivery_push role's install behaviour in the existing Host provisioning tree section.

### Motivation

The role merged under the expedited incident gtx5nl (livespec-dev-tooling-gtx5nl, PR #5157, master d0cf7db82) and its repayment is held because no ratified heading states the role's behaviour: the Host provisioning tree section states only generic role obligations, and git grep caam SPECIFICATION finds only history files. The maintainer ruled (2026-11-22, recorded on 6tgd2z) that major changes belong in the non-functional requirements doc, or update the section they touch. The role's behaviour is host provisioning, so it belongs in the existing section; no new H2 is needed, so tests/heading-coverage.json is unchanged.

### Proposed Changes

In SPECIFICATION/non-functional-requirements.md, section '## Host provisioning tree', add the following paragraph immediately after the paragraph that begins '**A held service is still installed by a role.**' (no new heading):

**The caam binary role installs only the pinned binary.** The `caam_delivery_push` role MUST install the caam release the role pins into `~/.local/bin/caam` from the release's raw linux/amd64 asset, and only after the downloaded file's sha256 matches the sha256 the role pins. A checksum mismatch MUST refuse, MUST NOT install the downloaded file, and MUST NOT leave an unverified binary at the destination. The install MUST be guarded by the installed binary's `caam --version` reporting the pinned version, so a second apply of the role reports no change. The role MUST install only the binary: it MUST NOT create, read or write the caam vault or state, and it MUST NOT run caam against any account.
