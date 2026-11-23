"""The audit, rather than a claim, decides whether shared proof may be cited."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from livespec_dev_tooling import _incident_fleet_shared_surface as shared_surface
from livespec_dev_tooling import incident_fleet_audit as fleet_audit
from livespec_dev_tooling._incident_fleet_capabilities import SURFACE_CAPABILITY
from livespec_dev_tooling._incident_fleet_shared_surface import shared_surface_determination
from livespec_dev_tooling._incident_fleet_surface_files import SURFACE_ROOTS, surface_files
from livespec_dev_tooling._incident_fleet_types import (
    CapabilityEvidence,
    FleetAudit,
    SurfaceDisposition,
)
from livespec_dev_tooling.fleet._context import FleetMember
from livespec_dev_tooling.fleet.contract import Manifest
from livespec_dev_tooling.incident_fleet_audit import SURFACES, audit_incident_fleet

_CONFIG = Path(__file__).parents[2] / "config" / "incident-fleet-shared-surfaces.json"
_CONSUMER = "example/consumer"
_PROVER = "example/prover"
_RELEASE = "a" * 40


def _claim(*, surface: str, disposition: str = "not-applicable") -> CapabilityEvidence:
    return CapabilityEvidence(
        repository=_CONSUMER,
        surface=surface,
        disposition=disposition,
        manifest_sha256="f" * 64,
        source_path="shared/build.py",
        release_build=_RELEASE,
        serving_build=_RELEASE,
        proof_ref=f"{_CONSUMER}: committed proof",
        owner="example",
        incident_item="" if disposition == "implemented" else "not-used",
        cumulative_scope="" if disposition == "implemented" else "d" * 64,
        normal_factory_proof="" if disposition == "implemented" else "not-used",
        reason="the fixture makes this unrelated surface inapplicable"
        if disposition == "not-applicable"
        else "",
    )


def _citation(*, surface: str, release: str = _RELEASE) -> CapabilityEvidence:
    return CapabilityEvidence(
        **{
            **_claim(surface=surface, disposition="implemented").__dict__,
            "proving_repository": _PROVER,
            "proving_incident_item": "example-proving-incident",
            "proving_release_build": release,
        }
    )


def _audit(*, claims: tuple[CapabilityEvidence, ...], authentic: bool = True) -> FleetAudit:
    return audit_incident_fleet(
        manifest=Manifest(
            owner="example",
            members=(
                FleetMember(repo="consumer", repo_class="enforcement-suite"),
                FleetMember(repo="prover", repo_class="enforcement-suite"),
            ),
            adopters=(),
        ),
        manifest_sha256="f" * 64,
        evidence=claims,
        verify_manifest=lambda _manifest, _digest: True,
        verify_evidence=lambda _claim: True,
        verify_proving_incident=lambda _claim: authentic,
    )


def _consumer_claims(*, citation: CapabilityEvidence) -> tuple[CapabilityEvidence, ...]:
    return tuple(
        citation if surface == citation.surface else _claim(surface=surface) for surface in SURFACES
    )


def _row(*, audit: FleetAudit, surface: str) -> SurfaceDisposition:
    return next(row for row in audit.rows if row.repository == _CONSUMER and row.surface == surface)


def test_committed_determinations_cover_every_surface_and_pin_the_shared_reader_inputs() -> None:
    document = json.loads(_CONFIG.read_text(encoding="utf-8"))
    assert document["schema"] == 1
    assert set(document["surfaces"]) == set(SURFACES)
    pre_push = shared_surface_determination(surface="Pre-push")
    focused = shared_surface_determination(surface="Focused test selection")
    assert pre_push is not None and pre_push.fully_determined
    assert focused is not None and not focused.fully_determined
    assert focused.adopter_configuration == (
        ".livespec.jsonc",
        "[tool.livespec_dev_tooling] table",
    )
    roots = SURFACE_ROOTS["Pre-push"]
    files, absent = surface_files(
        roots=roots,
        read=lambda path: (Path(__file__).parents[2] / path).read_text(encoding="utf-8")
        if (Path(__file__).parents[2] / path).is_file()
        else None,
    )
    assert not absent
    assert set(roots) <= files
    assert SURFACE_CAPABILITY["Pre-push"] == "gate-readers"


@pytest.mark.parametrize(
    "document",
    [
        "{",
        "[]",
        "{}",
        '{"surfaces": {"Pre-push": []}}',
        '{"surfaces": {"Pre-push": {"fully_determined": true}}}',
        '{"surfaces": {"Pre-push": {"fully_determined": true, "adopter_configuration": [""]}}}',
    ],
)
def test_malformed_committed_surface_configuration_is_unusable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, document: str
) -> None:
    path = tmp_path / "shared-surfaces.json"
    _ = path.write_text(document, encoding="utf-8")
    monkeypatch.setattr(shared_surface, "_PATH", path)
    assert shared_surface.shared_surface_determination(surface="Pre-push") is None


@pytest.mark.integration
def test_shared_proof_classifies_only_when_the_surface_and_release_are_authenticated() -> None:
    accepted = _audit(claims=_consumer_claims(citation=_citation(surface="Pre-push")))
    assert _row(audit=accepted, surface="Pre-push").disposition == "implemented"

    focused = _audit(claims=_consumer_claims(citation=_citation(surface="Focused test selection")))
    finding = _row(audit=focused, surface="Focused test selection").reason
    assert _row(audit=focused, surface="Focused test selection").disposition == "unclassified"
    assert _CONSUMER in finding
    assert "Focused test selection" in finding
    assert ".livespec.jsonc" in finding

    later = _audit(
        claims=_consumer_claims(citation=_citation(surface="Pre-push", release="b" * 40))
    )
    assert _row(audit=later, surface="Pre-push").reason == (
        f"cited release {'b' * 40} differs from serving version read {_RELEASE}"
    )

    unauthenticated = _audit(
        claims=_consumer_claims(citation=_citation(surface="Pre-push")), authentic=False
    )
    assert "does not authenticate" in _row(audit=unauthenticated, surface="Pre-push").reason

    incomplete = _audit(
        claims=_consumer_claims(
            citation=CapabilityEvidence(
                **{
                    **_citation(surface="Pre-push").__dict__,
                    "proving_incident_item": "",
                }
            )
        )
    )
    assert _row(audit=incomplete, surface="Pre-push").reason == (
        "citing claim omits proving incident incident item"
    )


def test_a_citation_needs_a_shared_surface_with_committed_determination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    non_shared = _audit(
        claims=_consumer_claims(citation=_citation(surface="First-failure observer"))
    )
    assert _row(audit=non_shared, surface="First-failure observer").reason == (
        "First-failure observer is not served by a shared build"
    )

    def no_determination(*, surface: str) -> None:
        del surface

    monkeypatch.setattr(fleet_audit, "shared_surface_determination", no_determination)
    absent = _audit(claims=_consumer_claims(citation=_citation(surface="Pre-push")))
    assert _row(audit=absent, surface="Pre-push").reason == (
        "Pre-push has no committed shared-surface determination"
    )
