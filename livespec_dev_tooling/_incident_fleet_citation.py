"""Whether a citing claim may borrow another adopter's proving incident.

A shared-build release-keyed claim may cite the incident that proved the same release in
another adopter only where the audit's committed configuration records the surface as fully
determined by that build, and only when the cited incident authenticates as it would for a
claim of its own adopter: the proving adopter's committed claim for the same surface names
that incident item and release, and passes every check an own claim passes, including its
own serving read and independent re-read.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from livespec_dev_tooling._incident_fleet_capabilities import SURFACE_CAPABILITY
from livespec_dev_tooling._incident_fleet_row_gap import RowReaders, row_gap
from livespec_dev_tooling._incident_fleet_shared_surface import shared_surface_determination
from livespec_dev_tooling._incident_fleet_types import CapabilityEvidence

__all__: list[str] = ["citation_reader"]

_SHARED_BUILDS = frozenset({"gate-readers", "templates", "driver-hooks"})
_NO_CITATION = "a proving incident's own claim cannot itself cite another adopter's incident"


def _determination_gap(*, claim: CapabilityEvidence) -> str:
    """Why the surface cannot borrow proof; "" when the shared build fully determines it."""
    if SURFACE_CAPABILITY.get(claim.surface, "") not in _SHARED_BUILDS:
        return f"{claim.surface} is not served by a shared build"
    determination = shared_surface_determination(surface=claim.surface)
    if determination is None:
        return f"{claim.surface} has no committed shared-surface determination"
    if determination.fully_determined:
        return ""
    inputs = ", ".join(determination.adopter_configuration)
    return f"{claim.repository}: {claim.surface} reads adopter configuration: {inputs}"


def _authentication_gap(
    *,
    claim: CapabilityEvidence,
    proving: CapabilityEvidence | None,
    manifest_sha256: str,
    readers: RowReaders,
) -> str:
    """Why the cited incident's committed record does not authenticate; "" when it does."""
    if proving is None:
        return "the proving adopter has no committed claim for this surface"
    if (proving.incident_item, proving.release_build) != (
        claim.proving_incident_item,
        claim.proving_release_build,
    ):
        return "its committed claim names another incident item or release"
    if proving.disposition != "implemented" or proving.cites_proving_incident:
        return "its committed claim is not an implemented claim of its own incident"
    return row_gap(
        claim=proving,
        manifest_sha256=manifest_sha256,
        instruction_only=False,
        inapplicable=False,
        readers=readers,
    )


@dataclass(frozen=True, kw_only=True)
class _CitationReader:
    """Judges a citing claim; called positionally by the row reader, like its sibling readers."""

    indexed: Mapping[tuple[str, str], CapabilityEvidence]
    manifest_sha256: str
    own: RowReaders

    def __call__(self, claim: CapabilityEvidence) -> str:
        gap = _determination_gap(claim=claim)
        if gap:
            return gap
        read = claim.serving_build or "-"
        if claim.proving_release_build != claim.release_build:
            return (
                f"cited release {claim.proving_release_build} "
                f"differs from serving version read {read}"
            )
        why = _authentication_gap(
            claim=claim,
            proving=self.indexed.get((claim.proving_repository, claim.surface)),
            manifest_sha256=self.manifest_sha256,
            readers=self.own,
        )
        if why:
            return (
                f"cited release {claim.proving_release_build} for {claim.proving_repository} "
                f"incident {claim.proving_incident_item} does not authenticate ({why}); "
                f"serving version read {read}"
            )
        return ""


def citation_reader(
    *,
    indexed: Mapping[tuple[str, str], CapabilityEvidence],
    manifest_sha256: str,
    confirmed: Callable[[CapabilityEvidence], bool],
    explain: Callable[[CapabilityEvidence], str],
) -> Callable[[CapabilityEvidence], str]:
    """A reader naming why a citing claim may not classify; "" when it may.

    `indexed` holds every committed claim by (consumer, surface), each carrying the serving
    build read for it, so the cited incident is judged exactly as its own adopter's claim is.
    """
    own = RowReaders(confirmed=confirmed, explain=explain, citation=lambda _claim: _NO_CITATION)
    return _CitationReader(indexed=indexed, manifest_sha256=manifest_sha256, own=own)
