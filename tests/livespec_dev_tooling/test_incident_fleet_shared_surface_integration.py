"""The audit, rather than a claim, decides whether shared proof may be cited."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from livespec_dev_tooling import _incident_fleet_shared_surface as shared_surface
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

_ROOT = Path(__file__).parents[2]
_CONFIG = _ROOT / "config" / "incident-fleet-shared-surfaces.json"
_SHARED_BUILDS = frozenset({"gate-readers", "templates", "driver-hooks"})
# What a reader's file set may read from the adopter's repository, as the declared inputs name it.
_ADOPTER_INPUTS = {
    ".livespec.jsonc": re.compile(r"\.livespec\.jsonc"),
    "[tool.livespec_dev_tooling] table": re.compile(r"tool\.livespec_dev_tooling|load_config\("),
    "copier answers": re.compile(r"copier"),
    "repository variables": re.compile(r"\bvars\."),
}
_DETERMINED = "Acceptance and completion"
_DETERMINED_FILES = frozenset(
    {
        "livespec_dev_tooling/__init__.py",
        "livespec_dev_tooling/_incident_run_types.py",
        "livespec_dev_tooling/incident_run_evidence.py",
    }
)
_CONSUMER = "example/consumer"
_PROVER = "example/prover"
_RELEASE = "a" * 40
_ITEM = "example-proving-incident"


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
    return replace(
        _claim(surface=surface, disposition="implemented"),
        proving_repository=_PROVER,
        proving_incident_item=_ITEM,
        proving_release_build=release,
    )


def _proof(*, surface: str, **changes: str) -> CapabilityEvidence:
    """The proving adopter's own committed claim for the incident a citation names."""
    own = replace(
        _claim(surface=surface, disposition="implemented"),
        repository=_PROVER,
        incident_item=_ITEM,
        cumulative_scope="d" * 64,
        normal_factory_proof="the normal factory proof",
    )
    return replace(own, **changes)


def _audit(
    *, claims: tuple[CapabilityEvidence, ...], confirmed: set[str] | None = None
) -> FleetAudit:
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
        verify_evidence=lambda claim: confirmed is None or claim.repository in confirmed,
    )


def _consumer_claims(
    *, citation: CapabilityEvidence, proof: CapabilityEvidence | None
) -> tuple[CapabilityEvidence, ...]:
    own = tuple(
        citation if surface == citation.surface else _claim(surface=surface) for surface in SURFACES
    )
    return own if proof is None else (*own, proof)


def _row(*, audit: FleetAudit, surface: str) -> SurfaceDisposition:
    return next(row for row in audit.rows if row.repository == _CONSUMER and row.surface == surface)


def _read(path: str) -> str | None:
    file = _ROOT / path
    return file.read_text(encoding="utf-8") if file.is_file() else None


def test_every_committed_determination_is_held_by_its_readers_exact_file_set() -> None:
    document = json.loads(_CONFIG.read_text(encoding="utf-8"))
    assert document["schema"] == 1
    assert set(document["surfaces"]) == set(SURFACES)
    for surface in SURFACES:
        determination = shared_surface_determination(surface=surface)
        assert determination is not None, surface
        roots = SURFACE_ROOTS.get(surface)
        if roots is None or SURFACE_CAPABILITY[surface] not in _SHARED_BUILDS:
            # No exact file set to hold the claim against: never fully determined.
            assert not determination.fully_determined, surface
            assert determination.adopter_configuration, surface
            continue
        files, absent = surface_files(roots=roots, read=_read)
        assert not absent, surface
        read = {
            label
            for label, pattern in _ADOPTER_INPUTS.items()
            if any(pattern.search(_read(path) or "") for path in files)
        }
        if determination.fully_determined:
            assert not read, f"{surface} reads {sorted(read)}"
            assert determination.adopter_configuration == (), surface
        else:
            assert read <= set(determination.adopter_configuration), surface
            assert determination.adopter_configuration, surface


def test_the_determined_surface_is_pinned_to_its_exact_files_and_a_config_reading_one_is_not() -> (
    None
):
    files, absent = surface_files(roots=SURFACE_ROOTS[_DETERMINED], read=_read)
    assert not absent
    assert files == _DETERMINED_FILES
    determined = shared_surface_determination(surface=_DETERMINED)
    assert determined is not None and determined.fully_determined
    focused = shared_surface_determination(surface="Focused test selection")
    assert focused is not None and not focused.fully_determined
    assert {".livespec.jsonc", "[tool.livespec_dev_tooling] table"} <= set(
        focused.adopter_configuration
    )
    pre_push = shared_surface_determination(surface="Pre-push")
    assert pre_push is not None and not pre_push.fully_determined


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
    proof = _proof(surface=_DETERMINED)
    accepted = _audit(claims=_consumer_claims(citation=_citation(surface=_DETERMINED), proof=proof))
    assert _row(audit=accepted, surface=_DETERMINED).disposition == "implemented"

    focused = _audit(
        claims=_consumer_claims(
            citation=_citation(surface="Focused test selection"),
            proof=_proof(surface="Focused test selection"),
        )
    )
    finding = _row(audit=focused, surface="Focused test selection").reason
    assert _row(audit=focused, surface="Focused test selection").disposition == "unclassified"
    assert _CONSUMER in finding
    assert "Focused test selection" in finding
    assert ".livespec.jsonc" in finding

    other = "b" * 40
    cited_later = _audit(
        claims=_consumer_claims(
            citation=_citation(surface=_DETERMINED, release=other),
            proof=_proof(surface=_DETERMINED, release_build=other, serving_build=other),
        )
    )
    assert _row(audit=cited_later, surface=_DETERMINED).reason == (
        f"cited release {other} differs from serving version read {_RELEASE}"
    )

    consumer_later = _audit(
        claims=_consumer_claims(
            citation=replace(_citation(surface=_DETERMINED), serving_build=other), proof=proof
        )
    )
    reason = _row(audit=consumer_later, surface=_DETERMINED).reason
    assert _row(audit=consumer_later, surface=_DETERMINED).disposition == "unclassified"
    assert _RELEASE in reason
    assert other in reason

    incomplete = _audit(
        claims=_consumer_claims(
            citation=replace(_citation(surface=_DETERMINED), proving_incident_item=""),
            proof=proof,
        )
    )
    assert _row(audit=incomplete, surface=_DETERMINED).reason == (
        "citing claim omits proving incident incident item"
    )


@pytest.mark.parametrize(
    ("proof", "confirmed"),
    [
        pytest.param(None, None, id="the-proving-adopter-committed-no-claim"),
        pytest.param(_proof(surface=_DETERMINED, incident_item="another-item"), None, id="item"),
        pytest.param(
            _proof(surface=_DETERMINED, release_build="b" * 40, serving_build="b" * 40),
            None,
            id="proved-another-release",
        ),
        pytest.param(_proof(surface=_DETERMINED, disposition="not-applicable"), None, id="kind"),
        pytest.param(
            replace(_proof(surface=_DETERMINED), proving_repository=_CONSUMER),
            None,
            id="itself-a-citation",
        ),
        pytest.param(_proof(surface=_DETERMINED, manifest_sha256="e" * 64), None, id="identity"),
        pytest.param(_proof(surface=_DETERMINED, normal_factory_proof=""), None, id="incomplete"),
        pytest.param(_proof(surface=_DETERMINED, serving_build=""), None, id="unread"),
        pytest.param(_proof(surface=_DETERMINED), {_CONSUMER}, id="not-reconfirmed"),
    ],
)
def test_a_cited_incident_that_does_not_authenticate_leaves_the_row_unclassified(
    proof: CapabilityEvidence | None, confirmed: set[str] | None
) -> None:
    audit = _audit(
        claims=_consumer_claims(citation=_citation(surface=_DETERMINED), proof=proof),
        confirmed=confirmed,
    )
    row = _row(audit=audit, surface=_DETERMINED)
    assert row.disposition == "unclassified"
    assert row.reason.startswith(f"cited release {_RELEASE} for {_PROVER} incident {_ITEM}")
    assert "does not authenticate" in row.reason
    assert f"serving version read {_RELEASE}" in row.reason


def test_a_citation_needs_a_shared_surface_with_committed_determination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    non_shared = _audit(
        claims=_consumer_claims(
            citation=_citation(surface="First-failure observer"),
            proof=_proof(surface="First-failure observer"),
        )
    )
    assert _row(audit=non_shared, surface="First-failure observer").reason == (
        "First-failure observer is not served by a shared build"
    )

    def no_determination(*, surface: str) -> None:
        del surface

    monkeypatch.setattr(
        "livespec_dev_tooling._incident_fleet_citation.shared_surface_determination",
        no_determination,
    )
    absent = _audit(
        claims=_consumer_claims(
            citation=_citation(surface=_DETERMINED), proof=_proof(surface=_DETERMINED)
        )
    )
    assert _row(audit=absent, surface=_DETERMINED).reason == (
        f"{_DETERMINED} has no committed shared-surface determination"
    )
