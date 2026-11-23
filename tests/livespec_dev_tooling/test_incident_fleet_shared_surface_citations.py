"""Shared-build incident citations are committed claims, not caller assertions."""

from __future__ import annotations

import json
from pathlib import Path

from returns.result import Success

from livespec_dev_tooling._incident_fleet_sources import load_claims


def test_a_fully_determined_shared_surface_claim_accepts_another_adopters_proof(
    tmp_path: Path,
) -> None:
    """A citation names the prover's repository, incident item, and exact release."""
    evidence = {
        "schema": 1,
        "evidence": [
            {
                "repository": "livespec-ai/livespec-driver-claude",
                "surface": "Pre-push",
                "disposition": "implemented",
                "manifest_sha256": "a" * 64,
                "source_path": "livespec_dev_tooling/gate_remote_delegate.py",
                "release_build": "a" * 40,
                "proof_ref": "livespec-ai/livespec-dev-tooling: authenticated proving incident",
                "owner": "livespec-ai/livespec-dev-tooling",
                "incident_item": "",
                "cumulative_scope": "",
                "normal_factory_proof": "",
                "proving_repository": "livespec-ai/livespec-dev-tooling",
                "proving_incident_item": "livespec-dev-tooling-proving-incident",
                "proving_release_build": "a" * 40,
            }
        ],
    }
    claims_path = tmp_path / "claims.json"
    claims_path.write_text(json.dumps(evidence), encoding="utf-8")

    loaded = load_claims(path=claims_path)

    assert isinstance(loaded, Success)
    claim = loaded.unwrap()[0]
    assert (
        claim.proving_repository,
        claim.proving_incident_item,
        claim.proving_release_build,
    ) == (
        "livespec-ai/livespec-dev-tooling",
        "livespec-dev-tooling-proving-incident",
        "a" * 40,
    )
