"""The observer-owned trigger starts only its one green, bound repair."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import livespec_dev_tooling.incident_merge_trigger as trigger
from livespec_dev_tooling.incident_merge_forge import Green, NotGreen

_ARM = SimpleNamespace(incident_id="incident-1", pr_number=42, head_sha="a" * 40)


def _ready(monkeypatch: pytest.MonkeyPatch) -> tuple[Mock, Mock]:
    credential = SimpleNamespace(app_id="4242")
    forge = SimpleNamespace(token=str(object()))
    monkeypatch.setattr(
        trigger,
        "load_config",
        Mock(
            return_value=SimpleNamespace(
                incident_merge_integration_id=4242, recovery_bypass_integration_id=7
            )
        ),
    )
    monkeypatch.setattr(trigger, "load_merge_credential", Mock(return_value=credential))
    return Mock(return_value=forge), Mock(return_value=object())


def test_the_bound_labelled_green_arm_starts_only_its_own_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connect, make_reader = _ready(monkeypatch)
    monkeypatch.setattr(trigger, "has_incident_label", Mock(return_value=True))
    monkeypatch.setattr(
        trigger,
        "required_checks_verdict",
        Mock(return_value=Green(head_sha=_ARM.head_sha, contexts=frozenset({"ci-green"}))),
    )
    start = Mock(return_value=0)

    status = trigger.run(
        argv=[],
        read_arm=Mock(return_value=_ARM),
        connect=connect,
        make_reader=make_reader,
        start=start,
    )

    assert status == 0
    assert start.call_args.kwargs == {"unit_prefix": "livespec-incident-merge", "pr_number": 42}


def test_an_unbound_arm_never_connects_or_starts_a_runner() -> None:
    connect, make_reader, start = Mock(), Mock(), Mock()

    status = trigger.run(
        argv=[],
        read_arm=Mock(return_value="arm-unbound"),
        connect=connect,
        make_reader=make_reader,
        start=start,
    )

    assert status == 1
    connect.assert_not_called()
    make_reader.assert_not_called()
    start.assert_not_called()


def test_non_green_required_checks_are_recorded_without_starting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connect, make_reader = _ready(monkeypatch)
    monkeypatch.setattr(trigger, "has_incident_label", Mock(return_value=True))
    monkeypatch.setattr(
        trigger,
        "required_checks_verdict",
        Mock(return_value=NotGreen(head_sha=_ARM.head_sha, reason="ci-green (pending)")),
    )
    record, start = Mock(return_value=1), Mock()
    monkeypatch.setattr(trigger, "_record", record)

    status = trigger.run(
        argv=[],
        read_arm=Mock(return_value=_ARM),
        connect=connect,
        make_reader=make_reader,
        start=start,
    )

    assert status == 1
    assert record.call_args.kwargs["reason"] == "checks-not-green"
    start.assert_not_called()
