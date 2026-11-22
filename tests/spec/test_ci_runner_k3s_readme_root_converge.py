"""Root-owned boot converge is the normal README apply path for CI cache manifests.

The k3s admin kubeconfig is intentionally not an operator credential.  A README
that presents ``KUBECONFIG=/etc/rancher/k3s/k3s.yaml`` as its apply command
turns a manifest edit into an undocumented system:masters login.  The boot
converge service already applies the complete committed tree as root, so these
operator sections must direct edits through that service instead.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__: list[str] = []

_REPO_ROOT = Path(__file__).resolve().parents[2]
_K3S = _REPO_ROOT / "ci-runner" / "k3s" / "phase2"
_ROOT_APPLY = "sudo systemctl start converge-ci-stack.service"
_NON_ROOT_ADMIN_KUBECONFIG = "KUBECONFIG=/etc/rancher/k3s/k3s.yaml"

_OPERATING_SECTIONS = (
    (_K3S / "crates-proxy" / "README.md", "Operating it"),
    (_K3S / "warm-cache" / "pypi-proxy" / "README.md", "Operating it"),
    (_K3S / "warm-cache" / "README.md", "Operating it"),
    (_K3S / "warm-cache" / "README.md", "Applying it — the order, and what is already done"),
)


def _section(*, path: Path, heading: str) -> str:
    """Return one H2-or-H3 README section without allowing another section to satisfy it."""
    source = path.read_text(encoding="utf-8")
    matched = re.search(
        rf"^#{{2,3}} {re.escape(heading)}\n(?P<body>.*?)(?=^#{{2,3}} |\Z)",
        source,
        re.MULTILINE | re.DOTALL,
    )
    assert matched is not None, f"{path.relative_to(_REPO_ROOT)} must retain `{heading}`"
    return matched.group("body")


def test_ci_cache_readmes_route_manifest_apply_through_the_root_boot_converge() -> None:
    """Every affected section names the root service, never an operator admin-kubeconfig apply."""
    sections = {
        f"{path.relative_to(_REPO_ROOT)}: {heading}": _section(path=path, heading=heading)
        for path, heading in _OPERATING_SECTIONS
    }
    missing_root_apply = sorted(
        name for name, section in sections.items() if _ROOT_APPLY not in section
    )
    non_root_admin_kubeconfig = sorted(
        name for name, section in sections.items() if _NON_ROOT_ADMIN_KUBECONFIG in section
    )

    assert not missing_root_apply, (
        "the normal manifest apply path must be the root-owned "
        f"`{_ROOT_APPLY}` service invocation in every affected README section; "
        f"missing={missing_root_apply}"
    )
    assert not non_root_admin_kubeconfig, (
        "the README must not retain a by-hand `KUBECONFIG=/etc/rancher/k3s/k3s.yaml` "
        "command for an operator login: the service owns that admin credential and runs as root; "
        f"sections={non_root_admin_kubeconfig}"
    )
