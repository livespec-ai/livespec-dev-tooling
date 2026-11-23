"""The image leg retains one current image for every repository tag series.

The production hosts are the only place that can prove the timer's next-run
log, but this test executes the committed reclaimer against a Docker-shaped
store.  It makes the deletion decision observable without touching a host
daemon: the stub carries two series in one repository, an image re-tagged
inside the horizon despite an old build timestamp, and an image used by a
stopped container.  Only the old, superseded image may disappear.
"""

from __future__ import annotations

import os
from pathlib import Path

from tests.hang_guard import run_under_hang_guard

__all__: list[str] = []

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "ansible/roles/container_reclaim/files/container-reclaim.sh"

_DOCKER_STUB = r"""#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' "$*" >>"$STUB_DOCKER_LOG"

created="$(date -u -d '10 days ago' +%Y-%m-%dT%H:%M:%S.%NZ)"
recent="$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S.%NZ)"

case "${1:-}" in
    ps)
        # The stopped container is deliberately included: the role must regard
        # every container reference as a keep, not only live dispatches.
        printf 'stopped-container\n'
        ;;
    container)
        [[ ${2:-} == inspect && ${*: -1} == stopped-container ]]
        printf 'sha256:stopped-used\n'
        ;;
    image)
        case "${2:-}" in
            ls)
                # Docker's --format result consumed by the image-leg inventory:
                # repository, tag, then the untruncated image id.
                printf '%s\n' \
                    $'ghcr.io/example/sandbox\tpython-v1.0.0\tsha256:superseded' \
                    $'ghcr.io/example/sandbox\tpython-v2.0.0\tsha256:python-current' \
                    $'ghcr.io/example/sandbox\tpython-v3.0.0-build\tsha256:build-suffixed' \
                    $'ghcr.io/example/sandbox\tpython-rust-v1.0.0\tsha256:rust-current' \
                    $'ghcr.io/example/sandbox\trollback-v1.0.0\tsha256:recent-retagged' \
                    $'ghcr.io/example/sandbox\tused-v1.0.0\tsha256:stopped-used'
                ;;
            inspect)
                id="${*: -1}"
                case "$id" in
                    sha256:recent-retagged) printf '%s\t%s\n' "$created" "$recent" ;;
                    *) printf '%s\t%s\n' "$created" "$created" ;;
                esac
                ;;
            rm)
                for id in "${@:3}"; do
                    rm -f "$STUB_IMAGE_STATE/${id#sha256:}"
                done
                ;;
            prune)
                # This is Docker's legacy broad behaviour: it cannot know the
                # tag-series keep rule, so it removes every old unused marker.
                # The test must fail while the role delegates to this command.
                rm -f "$STUB_IMAGE_STATE/superseded" \
                    "$STUB_IMAGE_STATE/python-current" \
                    "$STUB_IMAGE_STATE/rust-current" \
                    "$STUB_IMAGE_STATE/recent-retagged"
                ;;
            *) exit 2 ;;
        esac
        ;;
    builder)
        [[ ${2:-} == prune ]]
        ;;
    *) exit 2 ;;
esac
"""


def _run_image_leg(*, tmp_path: Path) -> None:
    """Run the role's sourceable image leg against the test's fake daemon."""
    script = _SCRIPT
    assert script.is_file(), f"{script.relative_to(_REPO_ROOT)} must be committed"
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    docker = stub_dir / "docker"
    _ = docker.write_text(_DOCKER_STUB, encoding="utf-8")
    docker.chmod(0o755)
    image_state = tmp_path / "images"
    image_state.mkdir()
    for image_id in (
        "superseded",
        "python-current",
        "rust-current",
        "recent-retagged",
        "stopped-used",
        "build-suffixed",
    ):
        _ = (image_state / image_id).touch()
    log = tmp_path / "docker.log"
    log.touch()
    store = tmp_path / "store"
    store.mkdir()
    environment = os.environ | {
        "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}",
        "STUB_DOCKER_LOG": str(log),
        "STUB_IMAGE_STATE": str(image_state),
    }

    completed = run_under_hang_guard(
        [
            "bash",
            "-c",
            'source "$1"; prune_images 72 yes "$2"',
            "image-leg",
            str(script),
            str(store),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert not (image_state / "superseded").exists(), (
        "the old image superseded within python's tag series must be removed:\n"
        f"{completed.stdout + completed.stderr}"
    )
    assert (
        image_state / "python-current"
    ).exists(), "the newest python tag-series image must survive even when it is old"
    assert (
        image_state / "build-suffixed"
    ).exists(), "a tag with text after the PATCH component is its own series, not python's"
    assert (
        image_state / "rust-current"
    ).exists(), "a repository's python-rust series has its own newest-image keep"
    assert (
        image_state / "recent-retagged"
    ).exists(), "an image re-tagged within the idle horizon must use LastTagTime, not Created"
    assert (
        image_state / "stopped-used"
    ).exists(), "an image used by a stopped container must survive the image leg"
    assert "image rm sha256:superseded" in log.read_text(
        encoding="utf-8"
    ), "each selected image must be removed explicitly so its repository, tag and id can be logged"


def test_image_reclaim_keeps_the_newest_image_of_each_tag_series(*, tmp_path: Path) -> None:
    """Exercise all selection guards against two tag series in one repository."""
    _run_image_leg(tmp_path=tmp_path)
