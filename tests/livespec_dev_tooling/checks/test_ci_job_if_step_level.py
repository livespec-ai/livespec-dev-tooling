"""A job whose every step carries an event-naming `if:` is event-bound (livespec-dev-tooling-hf2x56).

livespec moved release-gate-pre-tag's release-only `if:` from the job onto each of its
steps. The job still runs on every event, but each step is skipped, so its members do
nothing outside a release-please pull request and must read as not run on that event.
"""

from __future__ import annotations

import pytest

from livespec_dev_tooling.checks._ci_job_if import event_bound_jobs

_EVENT = "github.event_name == 'pull_request' && startsWith(github.head_ref, 'release-please--')"


def _workflow(*, steps: str) -> str:
    return (
        "on: [push, pull_request]\n"
        "jobs:\n"
        "  gated:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        f"{steps}"
        "  plain:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: just check-y\n"
    )


def test_a_job_whose_every_step_names_the_event_in_its_if_is_event_bound():
    steps = (
        f"      - name: Checkout\n        if: ${{{{ {_EVENT} }}}}\n        uses: actions/checkout@v5\n"
        "      - if: ${{ github.head_ref != '' }}\n        run: just check-x\n"
    )
    assert event_bound_jobs(source=_workflow(steps=steps)) == frozenset({"gated"})


def test_a_job_with_one_unguarded_step_is_not_event_bound():
    steps = (
        f"      - if: ${{{{ {_EVENT} }}}}\n        run: just check-x\n      - run: just check-z\n"
    )
    assert event_bound_jobs(source=_workflow(steps=steps)) == frozenset()


def test_a_step_if_that_names_no_event_or_ref_leaves_the_job_not_event_bound():
    steps = (
        f"      - if: ${{{{ {_EVENT} }}}}\n        run: just check-x\n"
        "      - if: ${{ needs.setup.result == 'success' }}\n        run: just check-z\n"
    )
    assert event_bound_jobs(source=_workflow(steps=steps)) == frozenset()


def test_a_step_if_that_is_a_yaml_alias_fails_closed_as_event_bound():
    steps = "      - if: *release_only\n        run: just check-x\n"
    assert event_bound_jobs(source=_workflow(steps=steps)) == frozenset({"gated"})


def test_a_job_level_if_still_decides_before_any_step_is_read():
    source = (
        "on: push\n"
        "jobs:\n"
        "  gated:\n"
        "    runs-on: ubuntu-latest\n"
        "    if: github.ref == 'refs/heads/master'\n"
        "    steps:\n"
        "      - run: just check-x\n"
    )
    assert event_bound_jobs(source=source) == frozenset({"gated"})


@pytest.mark.parametrize(
    ("label", "steps_line"),
    [
        ("flow sequence of steps", "    steps: [{run: just check-x}]\n"),
        ("flow sequence with a trailing comment", "    steps: [{run: x}]  # inline\n"),
    ],
)
def test_a_steps_value_this_read_cannot_split_fails_closed_as_event_bound(
    *, label: str, steps_line: str
):
    source = f"on: push\njobs:\n  gated:\n    runs-on: ubuntu-latest\n{steps_line}"
    assert event_bound_jobs(source=source) == frozenset({"gated"}), label


def test_a_job_with_no_steps_is_not_event_bound():
    source = "on: push\njobs:\n  gated:\n    uses: ./.github/workflows/reusable.yml\n"
    assert event_bound_jobs(source=source) == frozenset()


def test_an_unindented_steps_list_is_read_like_an_indented_one():
    source = (
        "on: push\n"
        "jobs:\n"
        "  gated:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "    - if: github.event_name == 'push'\n"
        "      run: just check-x\n"
    )
    assert event_bound_jobs(source=source) == frozenset({"gated"})
