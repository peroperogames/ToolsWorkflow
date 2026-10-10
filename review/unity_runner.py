"""Unity host-project build, test and project-file generation.

UPM packages have no compilable C# project of their own. To analyse, compile and
test them reliably — with full UnityEngine references — the runner keeps one
persistent empty Unity project (``UNITY_HOST_PROJECT``, e.g. 2022.3.62f3). The
package under review is pulled in as a ``file:`` dependency, Unity generates the
real sln/csproj in batch mode, tests run, and ReSharper then inspects the
generated solution.

Caching lifecycle (per pull request):
  * first run (host does not yet reference the package) -> ``git clone`` the PR
    head into the cache and add the ``file:`` dependency;
  * later pushes -> ``git fetch`` + ``checkout`` the new head (no re-clone);
  * PR closed -> remove the dependency and delete the clone.

Every entry point is best-effort: any failure logs and degrades to "Unity step
skipped" rather than breaking the AI review.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

UNITY_TIMEOUT = int(os.environ.get("UNITY_TIMEOUT", "1800"))  # 30 min default


def log(message: str) -> None:
    print(message, file=sys.stderr)


# --------------------------------------------------------------------------- #
# Environment / availability
# --------------------------------------------------------------------------- #

def unity_path() -> Optional[str]:
    """Path to the Unity executable, or None when not configured/found."""
    path = os.environ.get("UNITY_PATH", "").strip()
    if path and os.path.exists(path):
        return path
    if path:
        log(f"UNITY_PATH set but not found: {path}")
    return None


def host_project() -> Optional[str]:
    """Path to the persistent Unity host project, or None when not configured."""
    host = os.environ.get("UNITY_HOST_PROJECT", "").strip()
    if host and os.path.isdir(host):
        return host
    if host:
        log(f"UNITY_HOST_PROJECT set but not a directory: {host}")
    return None


def cache_root() -> Path:
    base = os.environ.get("UNITY_CACHE_DIR", "").strip()
    if base:
        return Path(base)
    return Path(tempfile.gettempdir()) / "ai-review-pkgs"


def _pr_key(owner: str, repo: str, number: int) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in f"{owner}__{repo}")
    return f"{safe}__{number}"


# --------------------------------------------------------------------------- #
# manifest.json
# --------------------------------------------------------------------------- #

def _manifest_path(host: str) -> Path:
    return Path(host) / "Packages" / "manifest.json"


def _read_manifest(host: str) -> Dict[str, Any]:
    path = _manifest_path(host)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(host: str, data: Dict[str, Any]) -> None:
    path = _manifest_path(host)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def host_has_package(host: str, pkg_name: str) -> bool:
    """Is ``pkg_name`` already a dependency of the host project?"""
    try:
        deps = _read_manifest(host).get("dependencies") or {}
        return pkg_name in deps
    except (OSError, ValueError) as exc:
        log(f"Could not read host manifest: {exc}")
        return False


def _manifest_add(host: str, pkg_name: str, clone_pkg_root: str) -> None:
    data = _read_manifest(host)
    deps = data.setdefault("dependencies", {})
    # Unity wants forward slashes in a file: URL.
    deps[pkg_name] = "file:" + clone_pkg_root.replace("\\", "/")
    _write_manifest(host, data)


def _manifest_remove(host: str, pkg_name: str) -> None:
    try:
        data = _read_manifest(host)
        deps = data.get("dependencies") or {}
        if pkg_name in deps:
            del deps[pkg_name]
            _write_manifest(host, data)
    except (OSError, ValueError) as exc:
        log(f"Could not edit host manifest during cleanup: {exc}")


# --------------------------------------------------------------------------- #
# package clone / sync
# --------------------------------------------------------------------------- #

def _run_git(args: List[str], cwd: Optional[str] = None, timeout: int = 300) -> Tuple[int, str]:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, timeout=timeout, capture_output=True, text=True
    )
    return proc.returncode, (proc.stdout + proc.stderr)


def _authed_url(owner: str, repo: str, token: str) -> str:
    return f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"


def _package_name_and_root(clone_dir: Path) -> Tuple[Optional[str], Optional[str]]:
    """Find the package.json nearest the clone root and read its ``name``.

    Returns ``(package_name, package_root_dir)``. The package root is the folder
    that holds package.json — the host references that folder via ``file:``.
    """
    candidates = [clone_dir / "package.json", *sorted(clone_dir.rglob("package.json"))]
    for pkg_json in candidates:
        if not pkg_json.is_file():
            continue
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        name = (data.get("name") or "").strip()
        if name:
            return name, str(pkg_json.parent)
    return None, None


def ensure_package(
    host: str,
    owner: str,
    repo: str,
    number: int,
    head_sha: str,
    token: str,
) -> Optional[Tuple[str, str]]:
    """Make the host reference the PR's package at ``head_sha``.

    First run clones; later runs fetch+checkout. Returns
    ``(package_name, package_root)`` or None on failure.
    """
    clone_dir = cache_root() / _pr_key(owner, repo, number)

    if clone_dir.exists():
        log(f"Syncing cached package clone to {head_sha[:8]} ...")
        code, out = _run_git(["fetch", "origin", head_sha], cwd=str(clone_dir))
        if code != 0:
            # The sha may not be fetchable directly; fall back to a full fetch.
            code, out = _run_git(["fetch", "--all"], cwd=str(clone_dir))
        if code != 0:
            log(f"git fetch failed, re-cloning: {out[-300:]}")
            shutil.rmtree(clone_dir, ignore_errors=True)
        else:
            code, out = _run_git(["checkout", "--force", head_sha], cwd=str(clone_dir))
            if code != 0:
                log(f"git checkout failed, re-cloning: {out[-300:]}")
                shutil.rmtree(clone_dir, ignore_errors=True)

    if not clone_dir.exists():
        log(f"Cloning {owner}/{repo} into the package cache ...")
        clone_dir.parent.mkdir(parents=True, exist_ok=True)
        code, out = _run_git(
            ["clone", "--no-single-branch", _authed_url(owner, repo, token), str(clone_dir)]
        )
        if code != 0:
            log(f"git clone failed: {out[-300:]}")
            return None
        code, out = _run_git(["checkout", "--force", head_sha], cwd=str(clone_dir))
        if code != 0:
            log(f"git checkout {head_sha[:8]} failed: {out[-300:]}")
            return None

    pkg_name, pkg_root = _package_name_and_root(clone_dir)
    if not pkg_name or not pkg_root:
        log("No package.json with a name found in the clone; not a UPM package.")
        return None

    try:
        if not host_has_package(host, pkg_name):
            log(f"Adding {pkg_name} to the host project as a file: dependency.")
            _manifest_add(host, pkg_name, pkg_root)
    except (OSError, ValueError) as exc:
        log(f"Could not add the package to the host manifest: {exc}")
        return None

    return pkg_name, pkg_root


# --------------------------------------------------------------------------- #
# Unity batch-mode invocations
# --------------------------------------------------------------------------- #

def _editor_log_path() -> Path:
    return Path(tempfile.gettempdir()) / "ai-review-unity.log"


def run_unity(unity: str, host: str, extra_args: List[str], timeout: int) -> Tuple[int, str]:
    """Invoke Unity in batch mode; return (returncode, combined log text)."""
    log_file = _editor_log_path()
    cmd = [
        unity,
        "-batchmode",
        "-nographics",
        "-silent-crashes",
        "-projectPath",
        host,
        "-logFile",
        str(log_file),
        *extra_args,
    ]
    try:
        proc = subprocess.run(cmd, timeout=timeout, capture_output=True, text=True)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        log(f"Unity timed out after {timeout}s.")
        rc = -1
    text = ""
    try:
        text = log_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return rc, text


def _extract_compile_errors(log_text: str) -> List[Dict[str, Any]]:
    """Pull ``error CSxxxx`` lines out of a Unity/MSBuild log.

    Each: ``{file, line, code, message}`` with file relative where possible.
    """
    import re

    errors: List[Dict[str, Any]] = []
    seen: set = set()
    # e.g. Assets/Foo.cs(12,5): error CS0103: The name 'x' does not exist
    pattern = re.compile(
        r"([^\s(][^(]*?\.cs)\((\d+),\d+\):\s*error\s+(CS\d+):\s*(.+)"
    )
    for line in log_text.splitlines():
        m = pattern.search(line)
        if not m:
            continue
        key = (m.group(1), m.group(2), m.group(4).strip())
        if key in seen:
            continue
        seen.add(key)
        errors.append(
            {
                "file": m.group(1).replace("\\", "/"),
                "line": int(m.group(2)),
                "code": m.group(3),
                "message": m.group(4).strip(),
            }
        )
    return errors


def generate_and_build(unity: str, host: str) -> Tuple[bool, List[Dict[str, Any]], Optional[str]]:
    """Regenerate project files and compile the host project.

    Returns ``(ok, compile_errors, sln_path)``. ``ok`` is False when Unity
    reported a non-zero exit or compile errors were found.
    """
    sync_method = os.environ.get("UNITY_SYNC_METHOD", "").strip()
    methods = [sync_method] if sync_method else [
        "UnityEditor.SyncVS.SyncSolution",  # built-in, regenerates sln/csproj
    ]
    rc, text = -1, ""
    for method in methods:
        log(f"Unity: generating project files via {method} ...")
        rc, text = run_unity(
            unity, host, ["-executeMethod", method, "-quit"], UNITY_TIMEOUT
        )
        if rc == 0:
            break

    errors = _extract_compile_errors(text)
    # Locate the generated solution in the host project root.
    sln = None
    try:
        slns = sorted(Path(host).glob("*.sln"))
        sln = str(slns[0]) if slns else None
    except OSError:
        pass

    ok = rc == 0 and not errors
    if errors:
        log(f"Unity compile: {len(errors)} error(s).")
    elif rc != 0:
        log(f"Unity project generation exited {rc}.")
    return ok, errors, sln


def run_tests(unity: str, host: str) -> Tuple[bool, List[Dict[str, Any]]]:
    """Run EditMode tests; return ``(ok, failures)``.

    PlayMode is skipped by default (batch-mode PlayMode needs extra setup); set
    ``UNITY_TEST_PLATFORMS`` to a comma list to override.
    """
    platforms = [
        p.strip()
        for p in os.environ.get("UNITY_TEST_PLATFORMS", "EditMode").split(",")
        if p.strip()
    ]
    all_failures: List[Dict[str, Any]] = []
    any_ran = False
    for platform in platforms:
        results = Path(tempfile.gettempdir()) / f"ai-review-tests-{platform}.xml"
        if results.exists():
            results.unlink()
        log(f"Unity: running {platform} tests ...")
        rc, _text = run_unity(
            unity,
            host,
            ["-runTests", "-testPlatform", platform, "-testResults", str(results)],
            UNITY_TIMEOUT,
        )
        if results.exists():
            any_ran = True
            all_failures.extend(_parse_nunit(results))
    ok = any_ran and not all_failures
    if all_failures:
        log(f"Unity tests: {len(all_failures)} failing case(s).")
    elif not any_ran:
        log("Unity tests: no results produced.")
    return ok, all_failures


def _parse_nunit(path: Path) -> List[Dict[str, Any]]:
    """Return failing test cases from an NUnit 3 results XML."""
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


# --------------------------------------------------------------------------- #
# cleanup
# --------------------------------------------------------------------------- #

def cleanup(host: str, owner: str, repo: str, number: int) -> None:
    """Remove the PR's dependency from the host and delete its clone."""
    clone_dir = cache_root() / _pr_key(owner, repo, number)
    pkg_name, _root = _package_name_and_root(clone_dir) if clone_dir.exists() else (None, None)
    if host and pkg_name:
        _manifest_remove(host, pkg_name)
        log(f"Removed {pkg_name} from the host project.")
    shutil.rmtree(clone_dir, ignore_errors=True)
    log(f"Deleted package cache for PR #{number}.")


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #

class UnityResult:
    """Outcome of the Unity step, consumed by the review flow."""

    def __init__(self) -> None:
        self.ran = False
        self.compiled = True
        self.tests_ok = True
        self.compile_errors: List[Dict[str, Any]] = []
        self.test_failures: List[Dict[str, Any]] = []
        self.sln_path: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.compiled and self.tests_ok

    def summary(self) -> str:
        if not self.ran:
            return ""
        if self.ok:
            return "✅ Unity: 编译通过,单元测试通过。"
        parts = []
        if not self.compiled:
            parts.append(f"编译失败({len(self.compile_errors)} 个错误)")
        if not self.tests_ok:
            parts.append(f"{len(self.test_failures)} 个单元测试失败")
        return "🔴 Unity: " + ";".join(parts) + "。"


def analyze(owner: str, repo: str, number: int, head_sha: str, token: str) -> UnityResult:
    """Full Unity step: ensure package -> build -> test. Never raises."""
    result = UnityResult()
    try:
        unity = unity_path()
        host = host_project()
        if not unity or not host:
            log("Unity not configured (UNITY_PATH / UNITY_HOST_PROJECT); skipping.")
            return result
        if not head_sha:
            log("No head sha; skipping Unity step.")
            return result

        ensured = ensure_package(host, owner, repo, number, head_sha, token)
        if not ensured:
            return result

        result.ran = True
        compiled, errors, sln = generate_and_build(unity, host)
        result.compiled = compiled
        result.compile_errors = errors
        result.sln_path = sln

        if compiled:
            tests_ok, failures = run_tests(unity, host)
            result.tests_ok = tests_ok
            result.test_failures = failures
        else:
            # No point testing code that does not compile.
            log("Skipping tests because compilation failed.")
        return result
    except Exception as exc:  # noqa: BLE001 - never break the review
        log(f"Unity step failed, continuing without it: {exc}")
        return result
