"""Memory-pressure headroom for the two K3s runner-pool nodes.

The node profile is the role's input and the ``kubelet-args.yaml.j2`` drop-in
renders every whitespace-delimited record as one ``kubelet-arg+`` entry.  These
are deliberately profile assertions: sizing is a per-node fact, while the role
is shared by every ``ci_pool`` member.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

__all__: list[str] = []

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROFILES = _REPO_ROOT / "ci-runner" / "k3s" / "phase0-bare-metal" / "profiles"
_TEMPLATE = _REPO_ROOT / "ansible" / "roles" / "k3s_config" / "templates" / "kubelet-args.yaml.j2"
_TARGET_NODES = ("gmktec-xubuntu", "poweredge-xubuntu")
_PROFILE_KUBELET_ARGS = re.compile(r"^KUBELET_ARGS=(?P<value>.*)$", re.MULTILINE)
_RENDERED_KUBELET_ARGS = re.compile(r"^kubelet-arg\+: (?P<records>\[.*\])$", re.MULTILINE)
_MEMORY_QUANTITY = re.compile(r"^(?P<value>[1-9][0-9]*)(?P<unit>Ki|Mi|Gi)$")


def _profile_kubelet_args(*, node: str) -> str:
    """Read the profile field exactly as the role's regex task does."""
    profile = _PROFILES / f"{node}.env"
    match = _PROFILE_KUBELET_ARGS.search(profile.read_text(encoding="utf-8"))
    assert match is not None, f"{profile.relative_to(_REPO_ROOT)} must declare KUBELET_ARGS"
    return match["value"]


def _rendered_records(*, args: str) -> list[str]:
    """Render the simple one-variable template without making Ansible a test dependency."""
    template = _TEMPLATE.read_text(encoding="utf-8")
    rendered = template.replace("{{ k3s_config_kubelet_arg_records }}", json.dumps(args.split()))
    match = _RENDERED_KUBELET_ARGS.search(rendered)
    assert match is not None, (
        f"{_TEMPLATE.relative_to(_REPO_ROOT)} must render one kubelet-arg+ record list; "
        f"rendered={rendered!r}"
    )
    return json.loads(match["records"])


def _memory_term(*, records: list[str], flag: str) -> str:
    """Return one non-zero memory term from a named kubelet argument."""
    prefix = f"{flag}="
    matching = [record.removeprefix(prefix) for record in records if record.startswith(prefix)]
    assert len(matching) == 1, f"expected one {flag} record, got {matching!r}; records={records!r}"
    if flag.startswith("eviction-"):
        match = re.search(r"(?:^|,)memory\.available<(?P<quantity>[^,]+)", matching[0])
        assert match is not None, f"{flag} must set memory.available; value={matching[0]!r}"
        quantity = match["quantity"]
    else:
        terms = dict(term.split("=", maxsplit=1) for term in matching[0].split(","))
        assert "memory" in terms, f"{flag} must reserve memory; terms={terms!r}"
        quantity = terms["memory"]
    assert _MEMORY_QUANTITY.fullmatch(quantity), (
        f"{flag} memory must be a positive binary quantity, not {quantity!r}"
    )
    return quantity


def test_runner_pool_profiles_render_memory_eviction_and_reservations_from_measured_sizing() -> None:
    """gmktec and poweredge reserve memory and evict before node-wide OOM pressure."""
    for node in _TARGET_NODES:
        profile = _PROFILES / f"{node}.env"
        profile_text = profile.read_text(encoding="utf-8")
        records = _rendered_records(args=_profile_kubelet_args(node=node))

        hard = _memory_term(records=records, flag="eviction-hard")
        soft = _memory_term(records=records, flag="eviction-soft")
        grace = [
            record.removeprefix("eviction-soft-grace-period=")
            for record in records
            if record.startswith("eviction-soft-grace-period=")
        ]
        assert len(grace) == 1 and "memory.available=" in grace[0], (
            f"{node} must give memory.available soft eviction a grace period; records={records!r}"
        )
        _memory_term(records=records, flag="kube-reserved")
        _memory_term(records=records, flag="system-reserved")
        assert re.search(r"measured.*peak.*working set", profile_text, re.IGNORECASE | re.DOTALL), (
            f"{profile.relative_to(_REPO_ROOT)} must record the measured peak factory-pod "
            "working set used to size its reservations and eviction thresholds"
        )
        assert re.search(r"measured.*(?:node memory|memory capacity)", profile_text, re.IGNORECASE | re.DOTALL), (
            f"{profile.relative_to(_REPO_ROOT)} must record the measured node-memory figure used "
            "to size its reservations and eviction thresholds"
        )
        assert hard != soft, (
            f"{node} needs distinct hard and soft memory.available thresholds so the soft grace "
            f"period has a meaningful earlier threshold; hard={hard}, soft={soft}"
        )
