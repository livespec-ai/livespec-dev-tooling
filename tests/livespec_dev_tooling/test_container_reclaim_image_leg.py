"""Executable coverage for ``container_reclaim``'s image-leg retention rule.

The rule is evaluated against Docker's inventory rather than against an image's
build age: every tag series keeps its newest image, a recently tagged rollback
survives despite an old ``Created`` time, and an image any container uses stays.
The test's Docker stand-in retains image metadata and container references in
plain files so it can exercise the committed timer script without a daemon.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

__all__: list[str] = []

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "ansible" / "roles" / "container_reclaim" / "files" / "container-reclaim.sh"
_REPOSITORY = "ghcr.io/example/sandbox"
_TIMEOUT_SECONDS = 120

_DOCKER_STUB = r"""#!/usr/bin/env bash
set -euo pipefail

images="$STUB_IMAGES"
containers="$STUB_CONTAINERS"
log="$STUB_LOG"

image_in_use() {
    awk -F '\t' -v image="$1" '$2 == image { found = 1 } END { exit !found }' "$containers"
}

remove_image() {
    local target="$1" temporary
    temporary="${images}.next"
    awk -F '\t' -v target="$target" '$1 != target && ($2 ":" $3) != target { print }' "$images" >"$temporary"
    mv "$temporary" "$images"
}

case "${1:-}" in
    info)
        printf '%s\n' "$STUB_DOCKER_ROOT"
        ;;
    ps)
        if [[ " $* " == *" --format "* ]]; then
            exit 0
        fi
        if [[ " $* " == *" -q "* || " $* " == *" -aq "* ]]; then
            awk -F '\t' '{ print $1 }' "$containers"
        fi
        ;;
    inspect)
        for argument in "$@"; do
            [[ "$argument" == c* ]] || continue
            awk -F '\t' -v container="$argument" '$1 == container { print $2 }' "$containers"
        done
        ;;
    container)
        [[ "${2:-}" == prune ]] || exit 2
        ;;
    builder)
        [[ "${2:-}" == prune ]] || exit 2
        ;;
    image)
        case "${2:-}" in
            ls)
                awk -F '\t' '{ print $2 "\t" $3 "\t" $1 "\t" $4 }' "$images"
                ;;
            inspect)
                for argument in "$@"; do
                    [[ "$argument" == sha256:* ]] || continue
                    awk -F '\t' -v image="$argument" '$1 == image { print $1 "\t" $4 "\t" $5 }' "$images"
                done
                ;;
            rm)
                target="${!#}"
                printf 'image-rm %s\n' "$target" >>"$log"
                remove_image "$target"
                ;;
            prune)
                while IFS=$'\t' read -r image repository tag created tagged; do
                    image_in_use "$image" && continue
                    printf 'image-prune %s:%s\n' "$repository" "$tag" >>"$log"
                    remove_image "$image"
                done < <(cat "$images")
                ;;
            *)
                exit 2
                ;;
        esac
        ;;
    *)
        exit 2
        ;;
esac
"""


class _DockerHost:
    """A file-backed Docker inventory with stopped-container references."""

    def __init__(self, *, tmp_path: Path) -> None:
        self._tmp_path = tmp_path
        self._bin = tmp_path / "bin"
        self._bin.mkdir()
        docker = self._bin / "docker"
        docker.write_text(_DOCKER_STUB, encoding="utf-8")
        docker.chmod(0o755)
        containerd = self._bin / "containerd"
        containerd.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
        containerd.chmod(0o755)
        hostname = self._bin / "hostname"
        hostname.write_text("#!/usr/bin/env sh\nprintf '%s\\n' test-host\n", encoding="utf-8")
        hostname.chmod(0o755)
        self._images = tmp_path / "images.tsv"
        self._images.touch()
        self._containers = tmp_path / "containers.tsv"
        self._containers.touch()
        self._log = tmp_path / "docker.log"
        self._log.touch()
        self._docker_root = tmp_path / "docker-root"
        self._docker_root.mkdir()
        self._host_env = tmp_path / "container-reclaim.env"
        self._host_env.write_text(
            "\n".join(
                (
                    "RECLAIM_CANONICAL_HOST=test-host",
                    "RECLAIM_SYSTEM_HOSTNAME=test-host",
                    "RECLAIM_CONTAINER_IDLE_HOURS=72",
                    "RECLAIM_IMAGE_IDLE_HOURS=72",
                )
            )
            + "\n",
            encoding="utf-8",
        )

    def add_image(self, *, image: str, tag: str, created: str, last_tagged: str) -> None:
        with self._images.open("a", encoding="utf-8") as inventory:
            inventory.write(f"{image}\t{_REPOSITORY}\t{tag}\t{created}\t{last_tagged}\n")

    def add_stopped_container(self, *, container: str, image: str) -> None:
        with self._containers.open("a", encoding="utf-8") as inventory:
            inventory.write(f"{container}\t{image}\n")

    def run(self) -> subprocess.CompletedProcess[str]:
        assert _SCRIPT.is_file(), f"{_SCRIPT.relative_to(_REPO_ROOT)} must be committed"
        environment = os.environ | {
            "PATH": f"{self._bin}{os.pathsep}{os.environ['PATH']}",
            "STUB_IMAGES": str(self._images),
            "STUB_CONTAINERS": str(self._containers),
            "STUB_LOG": str(self._log),
            "STUB_DOCKER_ROOT": str(self._docker_root),
        }
        return subprocess.run(
            ["bash", str(_SCRIPT), str(self._host_env), "--apply"],
            capture_output=True,
            check=False,
            env=environment,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )

    def image_ids(self) -> set[str]:
        return {
            line.split("\t", maxsplit=1)[0]
            for line in self._images.read_text(encoding="utf-8").splitlines()
        }


def test_image_reclaim_keeps_each_tag_series_newest_and_only_removes_aged_superseded_images(
    *, tmp_path: Path
) -> None:
    """Run the image leg against two tag series, a recent rollback and a stopped use."""
    host = _DockerHost(tmp_path=tmp_path)
    python_old = "sha256:python-old"
    python_new = "sha256:python-new"
    rust_old = "sha256:rust-old"
    rust_new = "sha256:rust-new"
    rollback = "sha256:rollback"
    rollback_newer = "sha256:rollback-newer"
    stopped = "sha256:stopped"
    stopped_newer = "sha256:stopped-newer"
    aged = "2026-01-01T00:00:00Z"
    recent = "2026-11-23T16:00:00Z"

    host.add_image(image=python_old, tag="python-v1.0.0", created=aged, last_tagged=aged)
    host.add_image(
        image=python_new, tag="python-v1.1.0", created="2026-02-01T00:00:00Z", last_tagged=aged
    )
    host.add_image(image=rust_old, tag="python-rust-v1.0.0", created=aged, last_tagged=aged)
    host.add_image(
        image=rust_new, tag="python-rust-v1.1.0", created="2026-03-01T00:00:00Z", last_tagged=aged
    )
    host.add_image(image=rollback, tag="rollback-v1.0.0", created=aged, last_tagged=recent)
    host.add_image(
        image=rollback_newer,
        tag="rollback-v1.1.0",
        created="2026-04-01T00:00:00Z",
        last_tagged=aged,
    )
    host.add_image(image=stopped, tag="stopped-v1.0.0", created=aged, last_tagged=aged)
    host.add_image(
        image=stopped_newer,
        tag="stopped-v1.1.0",
        created="2026-05-01T00:00:00Z",
        last_tagged=aged,
    )
    host.add_stopped_container(container="c-stopped", image=stopped)

    done = host.run()

    assert done.returncode == 0, done.stdout + done.stderr
    assert host.image_ids() == {
        python_new,
        rust_new,
        rollback,
        rollback_newer,
        stopped,
        stopped_newer,
    }, done.stdout + done.stderr
