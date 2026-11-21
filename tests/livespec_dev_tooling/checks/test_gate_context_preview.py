"""Behavioral tests for the factory gate PREVIEW disposition of an unreadable credential.

A factory Green preview runs a consumer's pre-commit hook inside the sandbox with
`LIVESPEC_GATE_CONTEXT=1` and `LIVESPEC_GATE_PREVIEW=1`. The sandbox credential holds
no admin scope, so a forge-admin member such as `check-branch-protection-alignment`
cannot read what it judges. The preview is feedback only (the pushing host re-runs the
member against the committed tree), so an unreadable read there MUST NOT count as a
failed target. A real delegated gate, with no preview signal, still fails closed.
"""

from __future__ import annotations

import pytest
import structlog

from livespec_dev_tooling.checks._gate_context import credential_skip_is_failure
from livespec_dev_tooling.checks.branch_protection_alignment import (
    _unreadable_protection_exit_code,
)

__all__: list[str] = []

_PREVIEW_ENV = {"LIVESPEC_GATE_CONTEXT": "1", "LIVESPEC_GATE_PREVIEW": "1"}


def test_a_preview_run_does_not_treat_an_unreadable_credential_as_failure() -> None:
    """The preview signal turns the strict gate disposition off."""
    assert credential_skip_is_failure(env=_PREVIEW_ENV) is False


def test_a_real_gate_without_the_preview_signal_still_fails_closed() -> None:
    """A delegated gate that authorises a push keeps the anti-vacuous disposition."""
    assert credential_skip_is_failure(env={"LIVESPEC_GATE_CONTEXT": "1"}) is True


def test_an_empty_preview_signal_reads_as_unset() -> None:
    """An empty preview value does not relax the gate."""
    env = {"LIVESPEC_GATE_CONTEXT": "1", "LIVESPEC_GATE_PREVIEW": ""}
    assert credential_skip_is_failure(env=env) is True


def test_branch_protection_exits_zero_for_an_unreadable_read_in_a_preview() -> None:
    """The branch-protection check passes a preview that could not read protection."""
    log = structlog.get_logger()
    assert _unreadable_protection_exit_code(log=log, env=_PREVIEW_ENV) == 0


def test_branch_protection_exits_one_for_an_unreadable_read_in_a_real_gate() -> None:
    """The branch-protection check still refuses a real gate that could not read protection."""
    log = structlog.get_logger()
    assert _unreadable_protection_exit_code(log=log, env={"LIVESPEC_GATE_CONTEXT": "1"}) == 1


def test_a_preview_names_the_skipped_member_and_the_credential_that_was_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The preview prints SKIPPED-UNREADABLE with the token variable, never its value."""
    env = {**_PREVIEW_ENV, "GH_TOKEN": "secret-value-not-to-print"}
    assert _unreadable_protection_exit_code(log=structlog.get_logger(), env=env) == 0
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "SKIPPED-UNREADABLE" in output
    assert "check-branch-protection-alignment" in output
    assert "GH_TOKEN" in output
    assert "secret-value-not-to-print" not in output


def test_a_preview_with_no_token_variable_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    """With no token variable set the skip line names the absence, not a credential."""
    assert _unreadable_protection_exit_code(log=structlog.get_logger(), env=_PREVIEW_ENV) == 0
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "SKIPPED-UNREADABLE" in output
    assert "no token variable" in output
