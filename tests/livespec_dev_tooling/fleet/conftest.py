"""Fleet-test package conftest — make sibling test-helper modules importable.

Under `--import-mode=importlib` (set in pyproject.toml) with no
`__init__.py` in the test tree, a test module cannot import a sibling
non-`test_*` helper by bare name or relative path: the directory is not
on `sys.path` and there is no parent package. Inserting this directory
onto `sys.path` here (conftest is imported before test collection) lets
the fleet test modules `from _protection_fixtures import ...` the shared
branch-protection payload helper.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_FLEET_TEST_DIR = Path(__file__).resolve().parent
if str(_FLEET_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_FLEET_TEST_DIR))


@pytest.fixture(autouse=True)
def _no_ambient_interim_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    """No fleet test's result may depend on the sandbox's own interim inputs file.

    Inside a factory sandbox the wrapper's owner-only `app-inputs.env` exists at the DEFAULT root,
    and the admin lane reads out-of-vantage on it, so a test that reaches the lane's `main()`
    without naming a root flips its verdict (livespec-dev-tooling-pugkxg). Every fleet test starts
    with the refresh root at a path that holds nothing and the plugins-root fallback cleared; the
    interim-context tests set their own root after this runs.
    """
    monkeypatch.setenv("LIVESPEC_SANDBOX_GH_REFRESH_ROOT", "/nonexistent/livespec-gh-refresh")
    monkeypatch.delenv("LIVESPEC_SANDBOX_CLAUDE_PLUGINS_ROOT", raising=False)
