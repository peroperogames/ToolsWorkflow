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
from typing import Any, Dict, List

# `Assets/Foo.cs(12,5): error CS0103: The name 'x' does not exist`
# MSBuild's shape, which Unity's editor log carries through unchanged.
_FILE_ERROR = re.compile(r"([^\s(][^(]*?\.(?:cs|fs))\((\d+),\d+\):\s*error\s+([A-Z]+\d+):\s*(.+)")
# `error NU1101: Unable to find package …` / `error MSB5004: …` — a failure with
# no source position, e.g. a restore that could not find a package.
_BARE_ERROR = re.compile(r"\berror\s+([A-Z]{2,}\d+):\s*(.+)")


def log(message: str) -> None:
    print(message, file=sys.stderr)


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
        failure = case.find("failure")
        if failure is not None:
            msg_el = failure.find("message")
            if msg_el is not None and msg_el.text:
                message = msg_el.text.strip()
        out.append({"name": name, "message": message})
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

    messages: Dict[str, str] = {}
    for element in tree.getroot().iter():
        if not element.tag.endswith("UnitTestResult"):
            continue
        if (element.get("outcome") or "").lower() != "failed":
            continue
        name = element.get("testName") or "unknown test"
        message = ""
        for child in element.iter():
            if child.tag.endswith("Message") and child.text:
                message = child.text.strip()
                break
        messages[name] = message

    for name, message in messages.items():
        out.append({"name": name, "message": message})
    return out
