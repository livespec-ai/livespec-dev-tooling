"""Which ci.yml jobs carry an `if:` that names the triggering event or ref.

A TOKEN test, never an evaluation (livespec-dev-tooling-yzr6ad): a job-level `if:`
mentioning any `github.event*`, `github.ref*`, `github.head_ref` or
`github.base_ref`, in dotted or bracket form, marks the job event-bound, and the
incident CI entrance lists that job's members as ones it does not run instead of
running or dropping them. A job gated only on `!cancelled()` or `needs.*.result`
(dev-tooling's coverage and metadata jobs) is not event-bound, so its members
keep running. The expression is read across a block scalar (`>-`, `|`) or a
multi-line plain value, and a trailing YAML comment is not part of it.

A job with no event-bound job-level `if:` is still event-bound when it has at least one
step and EVERY step carries an event-bound step-level `if:` (livespec-dev-tooling-hf2x56):
the job runs on every event but each step is skipped, so its members do nothing outside
the guarded event. One unguarded step keeps the job unconditional. A `steps:` value this
read cannot split (a flow sequence) fails closed as event-bound, like an unresolvable alias.
"""

from __future__ import annotations

import re
from itertools import takewhile

from livespec_dev_tooling.checks._ci_matrix_parse import job_blocks

__all__: list[str] = ["event_bound_jobs"]

_JOB_IF = re.compile(r"^(?P<indent> *)if:(?P<rest>.*)$")
_STEPS_KEY = re.compile(r"^(?P<indent> *)steps:(?P<rest>.*)$")
_BLOCK_SCALAR = re.compile(r"^[|>][-+0-9]*$")
_EVENT_OR_REF = r"(?:event|ref|head_ref|base_ref)\w*"
_EVENT_BOUND_TOKEN = re.compile(
    rf"\bgithub(?:\.{_EVENT_OR_REF}|\[\s*['\"]{_EVENT_OR_REF}['\"]\s*\])"
)


def _without_comment(*, text: str) -> str:
    """`text` up to a YAML comment: a `#` outside quotes that follows whitespace.

    Inside a double-quoted string a backslash escapes the next character, so an
    escaped quote does not end the string.
    """
    quote = ""
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
        elif quote == '"' and char == "\\":
            escaped = True
        elif quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "#" and (index == 0 or text[index - 1].isspace()):
            return text[:index]
    return text


def _condition_at(*, lines: list[str], indent: int) -> str:
    """The `if:` expression's text at key `indent` within `lines`, or the empty string."""
    for position, raw in enumerate(lines):
        match = _JOB_IF.match(raw)
        if match is None or len(match.group("indent")) != indent:
            continue
        head = _without_comment(text=match.group("rest")).strip()
        continuation: list[str] = []
        for following in lines[position + 1 :]:
            if len(following) - len(following.lstrip()) <= indent:
                break
            continuation.append(following)
        if _BLOCK_SCALAR.match(head):
            return "\n".join(continuation)
        return "\n".join([head, *(_without_comment(text=line) for line in continuation)])
    return ""


def _significant(*, body: list[str]) -> list[str]:
    return [raw for raw in body if raw.strip() and not raw.strip().startswith("#")]


def _job_level_condition(*, body: list[str]) -> str:
    """The job-level `if:` expression's text, or the empty string when there is none."""
    lines = _significant(body=body)
    indent = len(lines[0]) - len(lines[0].lstrip()) if lines else -1
    return _condition_at(lines=lines, indent=indent)


def _step_groups(*, body: list[str]) -> list[list[str]] | None:
    """Each step's lines, or None when the `steps:` value is a flow form this read cannot split."""
    lines = _significant(body=body)
    job_indent = len(lines[0]) - len(lines[0].lstrip()) if lines else -1
    for position, raw in enumerate(lines):
        match = _STEPS_KEY.match(raw)
        if match is None or len(match.group("indent")) != job_indent:
            continue
        if _without_comment(text=match.group("rest")).strip():
            return None
        block = list(
            takewhile(
                lambda line: _in_steps(line=line, job_indent=job_indent), lines[position + 1 :]
            )
        )
        item_width = len(block[0]) - len(block[0].lstrip()) if block else 0
        starts = [
            index
            for index, line in enumerate(block)
            if len(line) - len(line.lstrip()) == item_width and line.lstrip().startswith("- ")
        ]
        return [block[s:e] for s, e in zip(starts, [*starts[1:], len(block)], strict=True)]
    return []


def _in_steps(*, line: str, job_indent: int) -> bool:
    """A line still inside the `steps:` list: deeper than the job's keys, or a dash at them."""
    width = len(line) - len(line.lstrip())
    return width > job_indent or (width == job_indent and line.lstrip().startswith("- "))


def _step_condition(*, step: list[str]) -> str:
    """A step's `if:` text; the `- ` list marker counts as the key's own indentation."""
    first = step[0]
    width = len(first) - len(first.lstrip())
    key_lines = [" " * (width + 2) + first.lstrip()[2:], *step[1:]]
    return _condition_at(lines=key_lines, indent=width + 2)


def _event_bound(*, condition: str) -> bool:
    """A condition naming the event or ref, or a YAML alias this read cannot resolve."""
    return condition.startswith("*") or _EVENT_BOUND_TOKEN.search(condition) is not None


def _every_step_event_bound(*, body: list[str]) -> bool:
    """At least one step, each with an event-bound `if:`; an unsplittable `steps:` fails closed."""
    groups = _step_groups(body=body)
    if groups is None:
        return True
    return bool(groups) and all(
        _event_bound(condition=_step_condition(step=step)) for step in groups
    )


def event_bound_jobs(*, source: str) -> frozenset[str]:
    """Names of jobs whose `if:` (job-level, or on every step) names the triggering event or ref.

    A YAML alias value (`if: *name`) cannot be read here, so it fails closed:
    the job counts as event-bound.
    """
    return frozenset(
        name
        for name, body in job_blocks(source=source)
        if _event_bound(condition=_job_level_condition(body=body))
        or _every_step_event_bound(body=body)
    )
