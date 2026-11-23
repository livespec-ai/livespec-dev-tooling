"""The reconcile_runs HOST_VARS.md states what the dev-host memory-bounds drop-in sets.

The drop-in ``50-livespec-memory-bounds.conf`` that role ``dev_host_memory_bounds``
places on ``reconcile-runs.service`` sets only ``MemorySwapMax`` and
``OOMScoreAdjust``. This test holds the role's operator document to the drop-in's
committed template, so the document cannot again claim the drop-in overrides the
unit text's ``MemoryHigh`` or ``MemoryMax`` (livespec-dev-tooling-ba7ypx).
"""

# EXPEDITED_INCIDENT_RESPONSE flag: livespec-dev-tooling-elejm2
from __future__ import annotations

import re
from pathlib import Path

__all__: list[str] = []

_ROLES = Path(__file__).resolve().parents[2] / "ansible" / "roles"
_DOC = (_ROLES / "reconcile_runs" / "HOST_VARS.md").read_text()
_DROP_IN = (
    _ROLES / "dev_host_memory_bounds" / "templates" / "reconcile-memory-bounds.conf.j2"
).read_text()


def _flat(*, text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_drop_in_template_sets_only_swap_and_oom_keys() -> None:
    keys = set(re.findall(r"^([A-Za-z]+)=", _DROP_IN, flags=re.MULTILINE))
    assert keys == {"MemorySwapMax", "OOMScoreAdjust"}


def test_host_vars_names_the_two_keys_the_drop_in_sets() -> None:
    doc = _flat(text=_DOC)
    assert "sets only `MemorySwapMax=0` and `OOMScoreAdjust=500`" in doc


def test_host_vars_does_not_say_the_drop_in_wins_the_memory_bounds() -> None:
    doc = _flat(text=_DOC)
    assert "its memory bounds win over the unit text's" not in doc


def test_host_vars_says_the_unit_text_supplies_memory_and_cpu_for_every_tenant() -> None:
    doc = _flat(text=_DOC)
    assert "takes its `MemoryHigh`, `MemoryMax` and `CPUWeight` from" in doc
    assert "Only the dev host's `reconcile-runs.service` carries" in doc
