"""Audit incident surfaces across the canonical manifest, without enabling them."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace

from livespec_dev_tooling._incident_fleet_capabilities import SURFACE_CAPABILITY
from livespec_dev_tooling._incident_fleet_row_gap import row_gap
from livespec_dev_tooling._incident_fleet_shared_surface import shared_surface_determination
from livespec_dev_tooling._incident_fleet_types import (
    CapabilityEvidence,
    FleetAudit,
    SurfaceDisposition,
)
from livespec_dev_tooling.fleet.contract import Manifest

__all__: list[str] = ["SURFACES", "audit_incident_fleet"]

# EXPEDITED_INCIDENT_RESPONSE flag: livespec-dev-tooling-wlrlt2
# These are the ratified 37 distinct launch, authority and evidence surfaces.
# Runtime audit must survive archival of its originating planning thread.
SURFACES: tuple[str, ...] = (
    "Hook installation and wiring",
    "Pre-commit before mode selection",
    "Commit-msg and TDD",
    "Pre-push",
    "Explicit commands and parallel aggregation",
    "Fast-gate timing",
    "Focused test selection",
    "Touched-file coverage",
    "Full coverage producers/consumers",
    "Normal evidence caches",
    "Delegated pre-commit",
    "Delegated push/replay/explicit gates",
    "Gate renderer and pod",
    "Credential/environment boundaries",
    "Agent tool and stop guards",
    "PR mode transport",
    "CI matrix/batch/direct action",
    "CI dependency/aggregate/merge context",
    "Parity/completeness enforcement",
    "Spec enforcement and debt",
    "Workflow-edit authorization",
    "PR factory provenance",
    "Retrospective bypass audit",
    "Operator factory routing",
    "Incident ownership transfer",
    "Branch/PR resolution",
    "Acceptance and completion",
    "Normal master context",
    "First-failure observer",
    "Emergency revert and merge authority",
    "Existing reconciler coordination",
    "Recovery dependency independence",
    "Failed-run retention",
    "Late regression/cleanup",
    "Release and distribution",
    "Generated projects",
    "Closure/proof/archive",
)


_GUIDANCE_SURFACES = frozenset({"Agent tool and stop guards", "Operator factory routing"})
# The consumer's own incident installation; every other capability is a shared build.
_OWN_INSTALLATION = frozenset({"independent-controller", "recovery-authorization"})


def _consumers(*, manifest: Manifest) -> tuple[tuple[str, bool], ...]:
    return tuple((f"{manifest.owner}/{m.repo}", False) for m in manifest.members) + tuple(
        (manifest.adopter_repository(adopter=a), a.profile == ("instruction-only",))
        for a in manifest.adopters
    )


def _index_evidence(
    *, evidence: tuple[CapabilityEvidence, ...], consumers: tuple[tuple[str, bool], ...]
) -> tuple[dict[tuple[str, str], CapabilityEvidence], tuple[str, ...]]:
    expected = {repository for repository, _instruction_only in consumers}
    indexed: dict[tuple[str, str], CapabilityEvidence] = {}
    findings: list[str] = []
    for row in evidence:
        key = (row.repository, row.surface)
        if row.repository not in expected or row.surface not in SURFACES:
            findings.append(f"foreign evidence: {row.repository}: {row.surface}")
        elif key in indexed:
            findings.append(f"duplicate evidence: {row.repository}: {row.surface}")
        else:
            indexed[key] = row
    return indexed, tuple(findings)


def _judged(*, evidence: CapabilityEvidence | None, surface: str) -> CapabilityEvidence | None:
    """The claim as its row is judged: a ruled-normal row on a shared build drops that read.

    A shared gate-reader, template or driver-hooks build serves every consumer that pins
    this library, so it contradicts no deliberately-normal ruling; it stays printed.
    """
    if (
        evidence is not None
        and evidence.disposition == "deliberately-normal"
        and SURFACE_CAPABILITY.get(surface) not in _OWN_INSTALLATION
    ):
        return replace(evidence, serving_build="")
    return evidence


def _consumer_rows(  # noqa: PLR0913 — each reader and identity input is independently injected.
    *,
    repository: str,
    instruction_only: bool,
    manifest_sha256: str,
    indexed: dict[tuple[str, str], CapabilityEvidence],
    verify_evidence: Callable[[CapabilityEvidence], bool],
    explain: Callable[[CapabilityEvidence], str],
    citation: Callable[[CapabilityEvidence], str],
) -> tuple[SurfaceDisposition, ...]:
    rows: list[SurfaceDisposition] = []
    for surface in SURFACES:
        evidence = indexed.get((repository, surface))
        inapplicable = instruction_only and surface not in _GUIDANCE_SURFACES
        if inapplicable and evidence is None:
            rows.append(
                SurfaceDisposition(
                    repository=repository,
                    surface=surface,
                    disposition="not-applicable",
                    reason="authenticated instruction-only profile has no runtime obligation",
                )
            )
            continue
        gap = row_gap(
            claim=_judged(evidence=evidence, surface=surface),
            manifest_sha256=manifest_sha256,
            instruction_only=instruction_only,
            inapplicable=inapplicable,
            confirmed=verify_evidence,
            explain=explain,
            citation=citation,
        )
        if gap or evidence is None:
            rows.append(
                SurfaceDisposition(
                    repository=repository,
                    surface=surface,
                    disposition="unclassified",
                    reason=gap,
                    evidence=evidence,
                )
            )
        else:
            rows.append(
                SurfaceDisposition(
                    repository=repository,
                    surface=surface,
                    disposition=evidence.disposition,
                    reason=evidence.reason,
                    evidence=evidence,
                )
            )
    return tuple(rows)


def _ready(
    *, consumers: tuple[tuple[str, bool], ...], rows: tuple[SurfaceDisposition, ...]
) -> tuple[str, ...]:
    """A consumer is ready on its own proof: fully classified, none normal, one implemented."""
    return tuple(
        repository
        for repository, instruction_only in consumers
        if not instruction_only
        and not any(
            row.repository == repository
            and row.disposition in {"unclassified", "deliberately-normal"}
            for row in rows
        )
        and any(row.repository == repository and row.disposition == "implemented" for row in rows)
    )


def audit_incident_fleet(  # noqa: PLR0913 — the audit's authenticated reads remain explicit seams.
    *,
    manifest: Manifest,
    manifest_sha256: str,
    evidence: tuple[CapabilityEvidence, ...],
    verify_manifest: Callable[[Manifest, str], bool],
    verify_evidence: Callable[[CapabilityEvidence], bool],
    verify_proving_incident: Callable[[CapabilityEvidence], bool] | None = None,
    explain: Callable[[CapabilityEvidence], str] = lambda _row: "",
) -> FleetAudit:
    """Expand authenticated current membership, including every declared adopter.

    Verifiers are independently installed readers of committed membership and
    released serving proof, not candidate labels or caller-supplied receipt
    parsers. They must return False when their authoritative read is unavailable.
    `explain` may name why a claim cannot classify against what was read. Every unclassified
    row names its missing evidence: that reason when it names one, otherwise the first gap
    the row has (no claim, a malformed or foreign-identity claim, an unreadable or stale
    serving version, or a re-read that did not confirm it).
    This function creates no credentials, lifecycle records or activation effects.
    """
    consumers = _consumers(manifest=manifest)

    def citation_gap(
        *,
        claim: CapabilityEvidence,
    ) -> str:
        capability = SURFACE_CAPABILITY.get(claim.surface, "")
        determination = shared_surface_determination(surface=claim.surface)
        if capability not in {"gate-readers", "templates", "driver-hooks"}:
            return f"{claim.surface} is not served by a shared build"
        if determination is None:
            return f"{claim.surface} has no committed shared-surface determination"
        if not determination.fully_determined:
            inputs = ", ".join(determination.adopter_configuration)
            return f"{claim.repository}: {claim.surface} reads adopter configuration: {inputs}"
        if claim.proving_release_build != claim.release_build:
            return (
                f"cited release {claim.proving_release_build} differs from serving version read "
                f"{claim.serving_build or '-'}"
            )
        verifier = verify_proving_incident or verify_evidence
        if verifier(claim) is not True:
            return (
                f"cited release {claim.proving_release_build} for "
                f"{claim.proving_repository} incident {claim.proving_incident_item} "
                f"does not authenticate; serving version read {claim.serving_build or '-'}"
            )
        return ""

    names = tuple(repository for repository, _instruction_only in consumers)
    if (
        not manifest.owner
        or not names
        or len(set(names)) != len(names)
        or re.fullmatch(r"[0-9a-f]{64}", manifest_sha256) is None
        or verify_manifest(manifest, manifest_sha256) is not True
    ):
        return FleetAudit(
            manifest_sha256=manifest_sha256,
            rows=(),
            findings=("manifest membership or committed identity is unauthenticated",),
            ready_repositories=(),
        )
    indexed, invalid_evidence = _index_evidence(evidence=evidence, consumers=consumers)
    rows = tuple(
        row
        for repository, instruction_only in consumers
        for row in _consumer_rows(
            repository=repository,
            instruction_only=instruction_only,
            manifest_sha256=manifest_sha256,
            indexed=indexed,
            verify_evidence=verify_evidence,
            explain=explain,
            citation=lambda row: citation_gap(claim=row),
        )
    )
    findings = invalid_evidence + tuple(
        f"{row.repository}: {row.surface}: {row.reason}"
        for row in rows
        if row.disposition == "unclassified"
    )
    ready = () if invalid_evidence else _ready(consumers=consumers, rows=rows)
    return FleetAudit(
        manifest_sha256=manifest_sha256, rows=rows, findings=findings, ready_repositories=ready
    )
