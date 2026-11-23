"""An instruction-only adopter's runtime-surface claim is not a proving incident."""

from __future__ import annotations

from dataclasses import replace

from livespec_dev_tooling._incident_fleet_types import CapabilityEvidence
from livespec_dev_tooling.fleet._context import FleetMember
from livespec_dev_tooling.fleet.contract import Adopter, Manifest
from livespec_dev_tooling.incident_fleet_audit import SURFACES, audit_incident_fleet

_SURFACE = "Acceptance and completion"
_CONSUMER = "example/consumer"
_PROVER = "example/notes"
_RELEASE = "a" * 40
_ITEM = "example-proving-incident"


def _claim(*, repository: str, surface: str) -> CapabilityEvidence:
    return CapabilityEvidence(
        repository=repository,
        surface=surface,
        disposition="implemented",
        manifest_sha256="f" * 64,
        source_path="shared/build.py",
        release_build=_RELEASE,
        serving_build=_RELEASE,
        proof_ref=f"{repository}: committed proof",
        owner="example",
        incident_item=_ITEM,
        cumulative_scope="d" * 64,
        normal_factory_proof="the normal factory proof",
    )


def test_a_runtime_claim_of_an_instruction_only_adopter_does_not_authenticate_a_citation() -> None:
    citation = replace(
        _claim(repository=_CONSUMER, surface=_SURFACE),
        incident_item="",
        cumulative_scope="",
        normal_factory_proof="",
        proving_repository=_PROVER,
        proving_incident_item=_ITEM,
        proving_release_build=_RELEASE,
    )
    others = tuple(
        replace(
            _claim(repository=_CONSUMER, surface=surface),
            disposition="not-applicable",
            reason="the fixture makes this unrelated surface inapplicable",
        )
        for surface in SURFACES
        if surface != _SURFACE
    )
    audit = audit_incident_fleet(
        manifest=Manifest(
            owner="example",
            members=(FleetMember(repo="consumer", repo_class="enforcement-suite"),),
            adopters=(Adopter(repo="notes", profile=("instruction-only",), posture="none"),),
        ),
        manifest_sha256="f" * 64,
        evidence=(*others, citation, _claim(repository=_PROVER, surface=_SURFACE)),
        verify_manifest=lambda _manifest, _digest: True,
        verify_evidence=lambda _evidence: True,
    )
    row = next(r for r in audit.rows if r.repository == _CONSUMER and r.surface == _SURFACE)
    assert row.disposition == "unclassified"
    assert "does not authenticate" in row.reason
