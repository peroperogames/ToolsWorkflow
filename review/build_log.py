"""Parsing the build and test output the language runners produce.

Shared by :mod:`unity_runner` and :mod:`dotnet_runner`: both drive an MSBuild-
based toolchain, so both read the same compiler-error shape, and both end up with
a test report XML (NUnit from Unity, TRX from the .NET SDK).
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Sequence

# `Assets/Foo.cs(12,5): error CS0103: The name 'x' does not exist`
# MSBuild's shape, which Unity's editor log carries through unchanged.
_FILE_ERROR = re.compile(r"([^\s(][^(]*?\.(?:cs|fs))\((\d+),\d+\):\s*error\s+([A-Z]+\d+):\s*(.+)")
# `error NU1101: Unable to find package …` / `error MSB5004: …` — a failure with
# no source position, e.g. a restore that could not find a package.
_BARE_ERROR = re.compile(r"\berror\s+([A-Z]{2,}\d+):\s*(.+)")

# How much of a failure's detail the job log prints, in items. The pull request
# comment carries the same list for the author; the log is for the operator, and
# a thousand-line paste of the same error is not more useful than the first twenty.
REPORT_LIMIT = 20


def log(message: str) -> None:
    print(message, file=sys.stderr)


def format_duration(seconds: float) -> str:
    """A duration as the log shows it: ``8s``, ``2m 14s``, ``1h 03m``.

    Rounded to the second and cut to two units, because a build of 3721 seconds
    is usefully reported as an hour and two minutes and the remaining second is
    noise beside it.
    """
    try:
        total = max(0, int(round(float(seconds))))
    except (TypeError, ValueError):
        return "0s"
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def tail_lines(text: str, count: int = 40, limit: int = 6000) -> List[str]:
    """The last ``count`` lines that said anything, and no more than ``limit`` chars.

    For a run that produced no report: the end of its output is the whole
    diagnosis, and it is what has to reach the pull request — an editor that hung
    said everything it was going to say in its last few lines.
    """
    interesting = [line.rstrip() for line in text.splitlines() if line.strip()]
    tail = interesting[-count:]
    while tail and sum(len(line) + 1 for line in tail) > limit:
        tail.pop(0)
    return tail


def format_compile_errors(
    errors: Sequence[Dict[str, Any]], limit: int = REPORT_LIMIT
) -> List[str]:
    """One line per compile error: where it is, the code, what it says.

    A build that fails says how many errors it found; this is what turns that
    count into something the operator can act on without opening the editor log.
    Errors with no source position (a restore that could not find a package) print
    without one, exactly as they arrive.
    """
    lines: List[str] = []
    for err in errors[:limit]:
        where = f"{err['file']}:{err.get('line') or 0}: " if err.get("file") else ""
        code = err.get("code") or ""
        message = (err.get("message") or "").strip()
        lines.append(f"{where}{code}: {message}".rstrip(": "))
    if len(errors) > limit:
        lines.append(f"... and {len(errors) - limit} more")
    return lines


def format_failure_details(
    failures: Sequence[Dict[str, Any]],
    per_case: int = 1500,
    total: int = 45000,
) -> List[str]:
    """The failures with their messages and stack traces, for a comment.

    A pull request comment is the only place a reader of the failing run actually
    looks, and "AssertionException" on its own says nothing; the frames that say
    which line was on the wrong side of the assertion are what the author needs.
    Bounded twice — per case and in total — because GitHub rejects a comment over
    65536 characters, and a report that cannot be posted is worse than a short
    one. The whole XML is offered beside it as an artifact link.
    """
    blocks: List[str] = []
    used = 0
    for case in failures:
        name = case.get("name") or "unknown test"
        message = (case.get("message") or "").strip()[:per_case]
        stack = (case.get("stack") or "").strip()[:per_case]
        block = f"**{name}**\n"
        if message:
            block += f"```\n{message}\n```\n"
        if stack:
            block += f"```\n{stack}\n```\n"
        if used + len(block) > total:
            blocks.append(f"… 其余 {len(failures) - len(blocks)} 个失败用例见附带的报告文件。")
            break
        blocks.append(block)
        used += len(block)
    return blocks


def format_test_failures(
    failures: Sequence[Dict[str, Any]], limit: int = REPORT_LIMIT
) -> List[str]:
    """One line per failing case: its name and the first line of its message.

    The first line only: a failure message is a stack trace more often than a
    sentence, and the whole of it is already in the report file the caller names
    beside the list.
    """
    lines: List[str] = []
    for case in failures[:limit]:
        message = (case.get("message") or "").strip().splitlines()
        first = message[0][:200] if message else ""
        name = case.get("name") or "unknown test"
        lines.append(f"{name} — {first}" if first else str(name))
    if len(failures) > limit:
        lines.append(f"... and {len(failures) - limit} more")
    return lines


def parse_compile_errors(text: str) -> List[Dict[str, Any]]:
    """Compiler/build errors out of an MSBuild-style log.

    Each: ``{file, line, code, message}``. ``file``/``line`` are empty/0 for an
    error that carries no source position — the caller anchors those to a status
    comment instead of an inline one.
    """
    errors: List[Dict[str, Any]] = []
    seen: set = set()
    for line in text.splitlines():
        match = _FILE_ERROR.search(line)
        if match:
            file, line_no, code, message = (
                match.group(1).replace("\\", "/"),
                int(match.group(2)),
                match.group(3),
                match.group(4).strip(),
            )
        else:
            match = _BARE_ERROR.search(line)
            if not match:
                continue
            file, line_no, code, message = "", 0, match.group(1), match.group(2).strip()
        key = (file, line_no, code, message)
        if key in seen:
            continue
        seen.add(key)
        errors.append({"file": file, "line": line_no, "code": code, "message": message})
    return errors


def parse_nunit_failures(path: Path) -> List[Dict[str, Any]]:
    """Failing test cases from an NUnit 3 results XML (Unity's -runTests)."""
    out: List[Dict[str, Any]] = []
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError) as exc:
        log(f"Could not parse test results: {exc}")
        return out
    for case in tree.getroot().iter("test-case"):
        if (case.get("result") or "").lower() != "failed":
            continue
        name = case.get("fullname") or case.get("name") or "unknown test"
        message = ""
        stack = ""
        failure = case.find("failure")
        if failure is not None:
            msg_el = failure.find("message")
            if msg_el is not None and msg_el.text:
                message = msg_el.text.strip()
            stack_el = failure.find("stack-trace")
            if stack_el is not None and stack_el.text:
                stack = stack_el.text.strip()
        out.append({"name": name, "message": message, "stack": stack})
    return out


def parse_trx_failures(path: Path) -> List[Dict[str, Any]]:
    """Failing test cases from a VSTest TRX report (``dotnet test``).

    Element names carry a namespace whose version has changed over the years, so
    elements are matched on their local name rather than a fully qualified tag.
    """
    out: List[Dict[str, Any]] = []
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError) as exc:
        log(f"Could not parse the test report: {exc}")
        return out

    found: Dict[str, Dict[str, str]] = {}
    for element in tree.getroot().iter():
        if not element.tag.endswith("UnitTestResult"):
            continue
        if (element.get("outcome") or "").lower() != "failed":
            continue
        name = element.get("testName") or "unknown test"
        message = ""
        stack = ""
        for child in element.iter():
            if child.tag.endswith("Message") and child.text and not message:
                message = child.text.strip()
            elif child.tag.endswith("StackTrace") and child.text and not stack:
                stack = child.text.strip()
        found[name] = {"name": name, "message": message, "stack": stack}

    out.extend(found.values())
    return out
