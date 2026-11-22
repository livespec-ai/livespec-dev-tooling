"""An operator clears a retired chain's pre-merge arm; a landed commit is refused by name."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from livespec_dev_tooling._incident_observer_store import load_record, repository_lock
from livespec_dev_tooling._incident_observer_types import ObserverArm, ObserverArmQuery
from livespec_dev_tooling.incident_observer_admission import (
    arm_before_merge,
    observer_arm_admitted,
)
from livespec_dev_tooling.incident_observer_arm_clear import ObserverArmClear
from livespec_dev_tooling.incident_observer_service import ControllerService

# EXPEDITED_INCIDENT_RESPONSE flag: livespec-dev-tooling-s7yiut

_GIT = ("git", "-c", "user.name=t", "-c", "user.email=t@example.com")


def _git(*, repo: Path, args: tuple[str, ...]) -> str:
    done = subprocess.run([*_GIT, *args], cwd=repo, capture_output=True, check=True, text=True)
    return done.stdout.strip()


@pytest.fixture
def world(tmp_path):
    repo = tmp_path / "reference"
    repo.mkdir()
    _git(repo=repo, args=("init", "-q"))
    _git(repo=repo, args=("commit", "-q", "--allow-empty", "-m", "base"))
    on_master = _git(repo=repo, args=("rev-parse", "HEAD"))
    _git(repo=repo, args=("update-ref", "refs/remotes/origin/master", on_master))
    _git(repo=repo, args=("checkout", "-q", "-b", "side"))
    _git(repo=repo, args=("commit", "-q", "--allow-empty", "-m", "side"))
    off_master = _git(repo=repo, args=("rev-parse", "HEAD"))
    settings = SimpleNamespace(
        repository="owner/repo",
        repo=repo,
        state=tmp_path / "protected",
        reader=("/installed/reader",),
        reader_release="v0.283.0",
        control_secret=b"control" * 8,
        query_secret=b"query" * 8,
        webhook_secret=b"webhook" * 8,
        target_branch="master",
    )
    return settings, on_master, off_master


def _arm_for(*, head, incident="incident-1"):
    return ObserverArm(
        repository="owner/repo",
        incident_item_id=incident,
        attempt_id="repair-1",
        phase="repair",
        operation_id="repair-operation",
        generation=1,
        owner="controller",
        base_sha="e" * 40,
        head_sha=head,
        pr_number=55,
        required_jobs=("coverage",),
        controller_release="v1.170.0",
        controller_revision="b" * 40,
        authority_receipt=b'{"receipt":"x"}',
    )


def _arm(*, settings, arm):
    return arm_before_merge(
        directory=settings.state,
        arm=arm,
        expected_arm_id=None,
        authorize_current=lambda _: True,
        released_controller=lambda *_: True,
    )


def _clear_payload(*, arm_id, operation_id="clear-1", operator="chad", reason="chain retired"):
    return {
        "repository": "owner/repo",
        "arm_id": arm_id,
        "operation_id": operation_id,
        "operator": operator,
        "reason": reason,
    }


def _record(*, settings):
    with repository_lock(directory=settings.state, repository=settings.repository) as path:
        return load_record(path=path)


def _query(*, arm, arm_id):
    return ObserverArmQuery(
        repository=arm.repository,
        arm_id=arm_id,
        pr_number=arm.pr_number,
        base_sha=arm.base_sha,
        head_sha=arm.head_sha,
        receipt_digest=hashlib.sha256(arm.authority_receipt).hexdigest(),
    )


def _clear(*, settings, payload, landed=None):
    return ObserverArmClear(installation=settings, landed=landed).execute(payload=payload)


def test_clear_records_operator_and_reason_and_unadmits_the_arm(world):
    settings, _, off_master = world
    arm = _arm_for(head=off_master)
    armed = _arm(settings=settings, arm=arm)
    query = _query(arm=arm, arm_id=armed.receipt)
    assert observer_arm_admitted(directory=settings.state, query=query)
    result = _clear(
        settings=settings, payload=_clear_payload(arm_id=armed.receipt), landed=lambda _: False
    )
    assert result["status"] == "cleared" and result["cleared_arm_id"] == armed.receipt
    assert result["operator"] == "chad" and result["reason"] == "chain retired"
    assert result["authorizes_current_effects"] is False and len(result["receipt"]) == 64
    assert not observer_arm_admitted(directory=settings.state, query=query)
    stored = _record(settings=settings)
    assert stored["observer_arm_id"] is None and stored["observer_arm"] is None
    assert stored["arm_clears"]["clear-1"]["result"] == result
    assert stored["arm_clears"]["clear-1"]["cleared_arm"]["incident_item_id"] == "incident-1"


def test_next_arm_needs_no_compare_and_swap_after_clear(world):
    settings, _, off_master = world
    first = _arm(settings=settings, arm=_arm_for(head=off_master))
    second = _arm_for(head=off_master, incident="incident-2")
    assert _arm(settings=settings, arm=second).status == "refused"
    _ = _clear(
        settings=settings, payload=_clear_payload(arm_id=first.receipt), landed=lambda _: False
    )
    later = _arm(settings=settings, arm=second)
    assert later.status == "armed" and later.receipt != first.receipt


def test_clear_is_idempotent_and_conflicting_retries_refuse(world):
    settings, _, off_master = world
    armed = _arm(settings=settings, arm=_arm_for(head=off_master))
    payload = _clear_payload(arm_id=armed.receipt)
    first = _clear(settings=settings, payload=payload, landed=lambda _: False)
    again = _clear(settings=settings, payload=payload, landed=lambda _: pytest.fail("no recheck"))
    changed = _clear(settings=settings, payload=payload | {"reason": "other"})
    assert again == first
    assert changed["status"] == "refused" and "conflicts" in changed["reason"]


def test_clear_refuses_when_the_incident_commit_landed_on_master(world):
    settings, on_master, _ = world
    armed = _arm(settings=settings, arm=_arm_for(head=on_master))
    result = _clear(settings=settings, payload=_clear_payload(arm_id=armed.receipt))
    assert result["status"] == "refused"
    assert "landed on master" in result["reason"] and on_master in result["reason"]
    assert "incident-1" in result["reason"]
    assert _record(settings=settings)["observer_arm_id"] == armed.receipt


def test_clear_refuses_when_landing_cannot_be_established(world):
    settings, _, _ = world
    armed = _arm(settings=settings, arm=_arm_for(head="c" * 40))
    result = _clear(settings=settings, payload=_clear_payload(arm_id=armed.receipt))
    assert result["status"] == "refused" and "cannot establish" in result["reason"]
    assert _record(settings=settings)["observer_arm_id"] == armed.receipt


def test_default_landing_check_accepts_a_head_off_master(world):
    settings, _, off_master = world
    armed = _arm(settings=settings, arm=_arm_for(head=off_master))
    result = _clear(settings=settings, payload=_clear_payload(arm_id=armed.receipt))
    assert result["status"] == "cleared"


def test_clear_refuses_a_bound_arm_by_name(world):
    settings, _, off_master = world
    armed = _arm(settings=settings, arm=_arm_for(head=off_master))
    with repository_lock(directory=settings.state, repository=settings.repository) as path:
        record = load_record(path=path)
        record["observer_arm_bound"] = True
        _ = path.write_text(json.dumps(record))
    result = _clear(
        settings=settings,
        payload=_clear_payload(arm_id=armed.receipt),
        landed=lambda _: pytest.fail("bound arm needs no git read"),
    )
    assert result["status"] == "refused" and "bound to its master run" in result["reason"]


def test_clear_refuses_missing_or_other_arm(world):
    settings, _, off_master = world
    nothing = _clear(settings=settings, payload=_clear_payload(arm_id="f" * 64))
    _ = _arm(settings=settings, arm=_arm_for(head=off_master))
    other = _clear(settings=settings, payload=_clear_payload(arm_id="f" * 64))
    assert nothing["status"] == "refused" and "retained arm" in nothing["reason"]
    assert other["status"] == "refused" and "retained arm" in other["reason"]


@pytest.mark.parametrize(
    "change",
    [
        {"repository": "owner/other"},
        {"operator": ""},
        {"reason": ""},
        {"operation_id": "bad id"},
        {"arm_id": 5},
        {"extra": "x"},
    ],
)
def test_clear_refuses_malformed_requests(world, change):
    settings, _, _ = world
    payload = _clear_payload(arm_id="a" * 64) | change
    result = _clear(settings=settings, payload=payload)
    assert result["status"] == "refused" and "invalid" in result["reason"]


def test_missing_field_refuses(world):
    settings, _, _ = world
    payload = _clear_payload(arm_id="a" * 64)
    del payload["operator"]
    assert _clear(settings=settings, payload=payload)["status"] == "refused"


def _call(*, settings, path, payload, secret):
    body = json.dumps(payload).encode()
    environ = {
        "PATH_INFO": path,
        "REQUEST_METHOD": "POST",
        "CONTENT_LENGTH": str(len(body)),
        "HTTP_AUTHORIZATION": "Bearer " + secret.decode(),
        "wsgi.input": io.BytesIO(body),
    }
    application = ControllerService(installation=settings, recover=lambda _: "effect")
    responses = []
    out = b"".join(application(environ, lambda status, _headers: responses.append(status)))
    return responses[0], json.loads(out)


def test_route_needs_the_control_credential(world):
    settings, _, off_master = world
    armed = _arm(settings=settings, arm=_arm_for(head=off_master))
    payload = _clear_payload(arm_id=armed.receipt)
    denied, _ = _call(
        settings=settings, path="/clear-arm", payload=payload, secret=settings.query_secret
    )
    still_armed = _record(settings=settings)["observer_arm_id"] == armed.receipt
    status, result = _call(
        settings=settings, path="/clear-arm", payload=payload, secret=settings.control_secret
    )
    assert denied.startswith("40") and still_armed
    assert status.startswith("20") and result["status"] == "cleared"
