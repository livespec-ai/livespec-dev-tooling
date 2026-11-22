"""Verify the hook pod template preserves every Fabro sandbox image's PATH.

Kubernetes replaces an image environment variable when a pod spec supplies
the same name.  The ARC hook template therefore cannot merely prepend its own
tool directories to ``PATH``: it must retain every entry from each sandbox
image it can run.  This check derives those paths from the committed
Dockerfiles alone; it never asks a registry for an image's configuration.

Each Dockerfile below ``docker/fabro-sandbox/`` is discovered at runtime, so a
new image layer is checked without a parallel registry in this module.  Its
``FROM`` chain is followed through local image tags and terminates at the
committed upstream image's documented default PATH.  A local layer's
``ENV PATH=...`` lines are then expanded in Dockerfile order.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import NamedTuple

_VENDOR_DIR = Path(__file__).resolve().parent.parent / "_vendor"
if str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

import structlog  # noqa: E402  — vendor-path-aware import after sys.path insert.

__all__: list[str] = []

CHECK_PURITY = "tree-pure"


_SANDBOX_ROOT = Path("docker") / "fabro-sandbox"
_TEMPLATE_PATH = Path("ci-runner") / "k3s" / "phase2" / "arc" / "hook-pod-template.yaml"
_DEFAULT_PATHS: dict[str, tuple[str, ...]] = {
    "buildpack-deps:noble-scm": (
        "/usr/local/sbin",
        "/usr/local/bin",
        "/usr/sbin",
        "/usr/bin",
        "/sbin",
        "/bin",
    ),
}
_ARG = re.compile(r"^\s*ARG\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:=(?P<value>\S+))?\s*$")
_FROM = re.compile(r"^\s*FROM\s+(?P<image>\S+)(?:\s+AS\s+\S+)?\s*$", re.IGNORECASE)
_PATH = re.compile(r"^\s*ENV\s+PATH=(?P<value>\S+)\s*$")
_VARIABLE = re.compile(r"\$\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|\$(?P<bare>PATH)")
_JOB = re.compile(r"^\s*-\s+name:\s*\$job\s*$")
_PATH_NAME = re.compile(r"^\s*-\s+name:\s*PATH\s*$")
_PATH_VALUE = re.compile(r"^\s*value:\s*(?P<value>\S+)\s*$")


class _Dockerfile(NamedTuple):
    """The PATH-relevant portion of one sandbox Dockerfile."""

    image: str
    parent: str
    path_updates: tuple[str, ...]


class _Resolution(NamedTuple):
    """A derived PATH, or the reason its FROM chain could not be resolved."""

    entries: tuple[str, ...]
    problem: str | None


def _split_path(*, value: str) -> tuple[str, ...]:
    """Split a colon-delimited PATH, rejecting no meaningful entries."""
    return tuple(entry for entry in value.split(":") if entry)


def _arguments(*, lines: list[str]) -> dict[str, str]:
    """Return the Dockerfile's ARG defaults used by its FROM instruction."""
    defaults: dict[str, str] = {}
    for line in lines:
        match = _ARG.match(line)
        if match is not None and match["value"] is not None:
            defaults[match["name"]] = match["value"]
    return defaults


def _expand(*, value: str, arguments: dict[str, str], path: tuple[str, ...]) -> str:
    """Expand Docker ARGs and the inherited PATH in one Dockerfile value."""

    return _VARIABLE.sub(
        lambda match: _replacement(match=match, arguments=arguments, path=path), value
    )


def _replacement(*, match: re.Match[str], arguments: dict[str, str], path: tuple[str, ...]) -> str:
    """Expand one Dockerfile variable reference from a PATH assignment."""
    name = match["braced"] or match["bare"]
    if name == "PATH":
        return ":".join(path)
    return arguments.get(name, match.group(0))


def _read_dockerfile(*, path: Path) -> _Dockerfile | None:
    """Read the one FROM chain and each PATH update from a Dockerfile."""
    lines = path.read_text(encoding="utf-8").splitlines()
    arguments = _arguments(lines=lines)
    parent: str | None = None
    updates: list[str] = []
    for line in lines:
        from_match = _FROM.match(line)
        if from_match is not None and parent is None:
            parent = _expand(value=from_match["image"], arguments=arguments, path=())
        path_match = _PATH.match(line)
        if path_match is not None:
            updates.append(path_match["value"])
    if parent is None:
        return None
    return _Dockerfile(image=path.parent.name, parent=parent, path_updates=tuple(updates))


def _dockerfiles(*, root: Path) -> tuple[_Dockerfile, ...]:
    """Discover every sandbox image Dockerfile below ``root``."""
    discovered: list[_Dockerfile] = []
    for path in sorted(root.glob("*/Dockerfile")):
        dockerfile = _read_dockerfile(path=path)
        if dockerfile is not None:
            discovered.append(dockerfile)
    return tuple(discovered)


def _local_parent(*, reference: str, images: dict[str, _Dockerfile]) -> str | None:
    """Map a local ``livespec-fabro-sandbox:<layer>-dev`` reference to a layer."""
    tag = reference.rsplit(":", maxsplit=1)[-1]
    image = tag.removesuffix("-dev")
    return image if image in images else None


def _resolve(
    *, image: str, images: dict[str, _Dockerfile], resolving: tuple[str, ...] = ()
) -> _Resolution:
    """Resolve one image's complete PATH through local FROM parents."""
    if image in resolving:
        chain = " -> ".join((*resolving, image))
        return _Resolution(entries=(), problem=f"cyclic local FROM chain: {chain}")
    dockerfile = images[image]
    local_parent = _local_parent(reference=dockerfile.parent, images=images)
    if local_parent is not None:
        parent = _resolve(image=local_parent, images=images, resolving=(*resolving, image))
    elif dockerfile.parent in _DEFAULT_PATHS:
        parent = _Resolution(entries=_DEFAULT_PATHS[dockerfile.parent], problem=None)
    else:
        return _Resolution(
            entries=(),
            problem=(
                f"unrecognised upstream image {dockerfile.parent!r}; add its committed "
                "default PATH before this image can be checked"
            ),
        )
    if parent.problem is not None:
        return parent
    entries = parent.entries
    for update in dockerfile.path_updates:
        entries = _split_path(value=_expand(value=update, arguments={}, path=entries))
    return _Resolution(entries=entries, problem=None)


def _template_path(*, path: Path) -> tuple[str, ...] | None:
    """Return the PATH value assigned to the ARC template's ``$job`` container."""
    in_job = False
    expect_value = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if _JOB.match(line):
            in_job = True
            continue
        if not in_job:
            continue
        if _PATH_NAME.match(line):
            expect_value = True
            continue
        if expect_value:
            value = _PATH_VALUE.match(line)
            if value is not None:
                return _split_path(value=value["value"].strip("\"'"))
            expect_value = False
    return None


def _relative_order_is_preserved(
    *, image_path: tuple[str, ...], template_path: tuple[str, ...]
) -> bool:
    """Whether entries shared by both PATHs retain the image's relative order."""
    positions = tuple(template_path.index(entry) for entry in image_path)
    return positions == tuple(sorted(positions))


def main() -> int:
    """Report every sandbox image whose PATH the hook template does not preserve."""
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )
    log = structlog.get_logger("hook_template_sandbox_image_path")
    root = Path.cwd()
    template_path = _template_path(path=root / _TEMPLATE_PATH)
    if template_path is None:
        log.error("hook template $job container has no PATH value", path=_TEMPLATE_PATH.as_posix())
        return 1
    dockerfiles = _dockerfiles(root=root / _SANDBOX_ROOT)
    images = {dockerfile.image: dockerfile for dockerfile in dockerfiles}
    if not images:
        log.error("no sandbox image Dockerfiles found", path=_SANDBOX_ROOT.as_posix())
        return 1
    failures = False
    for image in sorted(images):
        resolution = _resolve(image=image, images=images)
        if resolution.problem is not None:
            log.error("cannot derive sandbox image PATH", image=image, problem=resolution.problem)
            failures = True
            continue
        missing = tuple(entry for entry in resolution.entries if entry not in template_path)
        for entry in missing:
            log.error(
                "sandbox image PATH entry missing from hook template PATH",
                image=image,
                entry=entry,
            )
        if missing:
            failures = True
            continue
        if not _relative_order_is_preserved(
            image_path=resolution.entries, template_path=template_path
        ):
            log.error("hook template PATH reorders sandbox image PATH entries", image=image)
            failures = True
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
