"""Consumer proof that the caam role's expedited-incident debt is repaid."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.consumer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ROLE_TEST = _REPO_ROOT / "tests" / "consumer" / "test_caam_delivery_push_role.py"


def test_the_caam_role_test_no_longer_carries_its_expedited_incident_marker() -> None:
    marker = "EXPEDITED_INCIDENT_RESPONSE flag: " + "livespec-dev-tooling-gtx5nl"

    assert marker not in _ROLE_TEST.read_text(encoding="utf-8")
