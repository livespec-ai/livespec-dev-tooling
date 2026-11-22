"""Behaviour coverage for the hook-template sandbox PATH checker.

The Red case proves the historical cargo omission.  These focused cases cover
the other failure modes that make the checker a durable guard: Dockerfile
expansion and inheritance, an automatically discovered new image, and a
template that reorders an inherited image PATH.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from livespec_dev_tooling.checks import hook_template_sandbox_image_path as check

__all__: list[str] = []


def _write(*, path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(text, encoding="utf-8")


def _template(*, root: Path, path: str) -> None:
    _write(
        path=root / "ci-runner/k3s/phase2/arc/hook-pod-template.yaml",
        text=(
            "spec:\n  containers:\n    - name: $job\n      env:\n"
            f"        - name: PATH\n          value: {path}\n"
        ),
    )


def _image(*, root: Path, name: str, parent: str, update: str = "") -> None:
    _write(
        path=root / "docker/fabro-sandbox" / name / "Dockerfile",
        text=f"FROM {parent}\n{update}",
    )


def test_path_helpers_expand_docker_arguments_and_reject_an_incomplete_template(
    *, tmp_path: Path
) -> None:
    """Parsing preserves Dockerfile arguments while requiring a complete PATH field."""
    dockerfile = tmp_path / "Dockerfile"
    _write(path=dockerfile, text="ARG IMAGE=buildpack-deps:noble-scm\nFROM ${IMAGE}\n")

    assert check._split_path(value="/one::/two:") == ("/one", "/two")  # noqa: SLF001
    assert check._arguments(lines=["ARG A=one", "ARG B"]) == {"A": "one"}  # noqa: SLF001
    assert (
        check._expand(  # noqa: SLF001
            value="${A}:$PATH:$MISSING",
            arguments={"A": "/one"},
            path=("/two",),
        )
        == "/one:/two:$MISSING"
    )
    assert check._read_dockerfile(path=dockerfile) == check._Dockerfile(  # noqa: SLF001
        image=tmp_path.name,
        parent="buildpack-deps:noble-scm",
        path_updates=(),
    )
    plain = tmp_path / "plain"
    _write(path=plain, text="ENV PATH=/one\n")
    assert check._read_dockerfile(path=plain) is None  # noqa: SLF001
    _write(path=tmp_path / "empty/Dockerfile", text="ENV PATH=/one\n")
    assert check._dockerfiles(root=tmp_path) == ()  # noqa: SLF001
    _write(
        path=tmp_path / "template",
        text="- name: $job\n- name: PATH\n- name: ANOTHER\n",
    )
    assert check._template_path(path=tmp_path / "template") is None  # noqa: SLF001


def test_new_sandbox_image_is_discovered_and_an_order_change_names_it(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A new image layer is discovered and its inherited ordering is enforced."""
    root = tmp_path / "repo"
    _image(
        root=root,
        name="base",
        parent="buildpack-deps:noble-scm",
        update="ENV PATH=/shims:/bin:$PATH\n",
    )
    _image(
        root=root,
        name="new-leaf",
        parent="livespec-fabro-sandbox:base-dev",
        update="ENV PATH=/tool:$PATH\n",
    )
    _template(
        root=root,
        path="/proxy:/tool:/bin:/shims:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin",
    )
    monkeypatch.chdir(root)

    assert check.main() == 1
    assert "new-leaf" in capsys.readouterr().err


def test_resolution_reports_unknown_and_cyclic_dockerfile_parents(*, tmp_path: Path) -> None:
    """A changed FROM chain fails closed instead of assuming an upstream PATH."""
    root = tmp_path / "docker/fabro-sandbox"
    _image(root=tmp_path, name="unknown", parent="example.invalid/image:latest")
    _image(root=tmp_path, name="left", parent="livespec-fabro-sandbox:right-dev")
    _image(root=tmp_path, name="right", parent="livespec-fabro-sandbox:left-dev")
    images = {item.image: item for item in check._dockerfiles(root=root)}  # noqa: SLF001

    unknown_problem = check._resolve(image="unknown", images=images).problem  # noqa: SLF001
    cycle_problem = check._resolve(image="left", images=images).problem  # noqa: SLF001
    assert unknown_problem is not None and "unrecognised upstream image" in unknown_problem
    assert cycle_problem is not None and "cyclic local FROM chain" in cycle_problem
    assert (
        check._local_parent(  # noqa: SLF001
            reference="example.invalid/image:latest", images=images
        )
        is None
    )


def test_main_reports_absent_inputs_and_unresolvable_images(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Malformed template and Dockerfile inputs fail with an actionable diagnostic."""
    monkeypatch.chdir(tmp_path)
    _write(
        path=tmp_path / "ci-runner/k3s/phase2/arc/hook-pod-template.yaml",
        text="spec:\n",
    )
    assert check.main() == 1
    assert "has no PATH value" in capsys.readouterr().err

    _template(root=tmp_path, path="/bin")
    assert check.main() == 1
    assert "no sandbox image Dockerfiles found" in capsys.readouterr().err

    _image(root=tmp_path, name="unknown", parent="example.invalid/image:latest")
    assert check.main() == 1
    assert "cannot derive sandbox image PATH" in capsys.readouterr().err
