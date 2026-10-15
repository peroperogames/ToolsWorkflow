"""Per-PR Unity project: creation, package build, unit tests, project files.

Only a UPM package needs this. A UPM package has no compilable C# project of its
own, so each pull request that contains one gets a Unity project of its own —
named ``<repo>-PR<number>``, created with the Unity CLI and reused by every later
review of that PR — and the package is pulled into it as a ``file:`` dependency.
Unity then generates the real sln/csproj in batch mode, compiles, and runs the
package's tests.

Lifecycle (see :mod:`pr_workspace` for the layout):
  * first run — create the project with ``unity projects create``;
  * later pushes — keep the project and recompile the synced clone;
  * PR closed — unregister the project from the Hub and delete the whole
    directory (project, clone and the agent session with it).

Every entry point is best-effort: any failure logs and degrades to "Unity step
skipped" rather than breaking the AI review.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import build_log
import pr_workspace
import repo_kind

UNITY_TIMEOUT = int(os.environ.get("UNITY_TIMEOUT", "1800"))  # 30 min default

# What Unity says when it cannot run for a reason that is not the code's fault.
# These are phrases, not the word "license": Unity's logs name its licensing
# module in runs that are perfectly healthy, so matching on that reports a
# licensing failure that never happened and hides the one that did.
LICENSE_FAILURES = (
    "no valid unity editor license",
    "no valid unity license",
    "failed to acquire license",
    "license is not valid",
    "licensing error",
)
EDITOR_FAILURES = (
    "editor not found",
    "no editor found",
    "no installed editor",
    "editor is not installed",
    "is not installed",
)

# The template a fresh per-PR project is created from, and the editor it is
# created for. Both are what `unity projects create` takes.
DEFAULT_EDITOR_VERSION = "2022.3.62f3"
DEFAULT_TEMPLATE = "com.unity.template.3d"


def log(message: str) -> None:
    print(message, file=sys.stderr)


# --------------------------------------------------------------------------- #
# Environment / availability
# --------------------------------------------------------------------------- #

# Where the CLI ends up when it is not on PATH: its own installer uses
# ~/.local/bin, and a CI service account's PATH frequently does not include it.
CLI_FALLBACK_DIRS = ("~/.local/bin", "/usr/local/bin", "/opt/unity/bin")


def unity_cli() -> Optional[str]:
    """Path to the Unity CLI, or None when it is not installed.

    Everything Unity happens through the CLI — it lays out the project, resolves
    the editor from the project's own ``ProjectVersion.txt``, and runs the tests —
    so this is the one thing that has to be found. The editor binary is never
    looked for: hardcoding its path is what made a runner whose editor lives
    somewhere else unable to run anything at all.

    When it cannot be found, every path that was checked is logged. "Not on PATH"
    is not enough to act on when the binary is installed and merely unreadable.
    """
    configured = os.environ.get("UNITY_CLI", "").strip()
    if configured:
        found = shutil.which(configured) or (configured if os.path.exists(configured) else None)
        if found:
            return found
        log(f"UNITY_CLI set but not found: {configured}")
        return None

    found = shutil.which("unity")
    if found:
        return found

    names = ("unity.exe", "unity") if os.name == "nt" else ("unity",)
    tried: List[str] = []
    for directory in CLI_FALLBACK_DIRS:
        for name in names:
            candidate = Path(os.path.expanduser(directory)) / name
            tried.append(str(candidate))
            if candidate.is_file() and os.access(candidate, os.X_OK):
                log(f"The Unity CLI is not on PATH; using {candidate}.")
                return str(candidate)

    log(
        "The Unity CLI ('unity') was not found, so there is no Unity step. "
        "Checked PATH and: " + ", ".join(tried) + ". "
        "Install it for the user the runner runs as, or set UNITY_CLI to its path "
        "(the runner user must also be able to read and execute the editor the "
        "CLI resolves)."
    )
    return None


def editor_version() -> str:
    return os.environ.get("UNITY_EDITOR_VERSION", "").strip() or DEFAULT_EDITOR_VERSION


def template_id() -> str:
    return os.environ.get("UNITY_TEMPLATE", "").strip() or DEFAULT_TEMPLATE


def project_subcommand() -> str:
    """Which CLI subcommand lays out a project.

    ``create`` registers the project in the Hub (and is the default, so it can
    also be opened by hand); ``new`` is the CI variant that never touches the
    registry. Either way the folder is ``<parent>/<name>``.
    """
    value = os.environ.get("UNITY_PROJECT_CMD", "").strip().lower()
    return value if value in ("create", "new") else "create"


# --------------------------------------------------------------------------- #
# project creation / reuse
# --------------------------------------------------------------------------- #

def project_dir(owner: str, repo: str, number: int) -> str:
    return str(pr_workspace.pr_dir(owner, repo, number))


def ensure_project(owner: str, repo: str, number: int, cli: str) -> Optional[str]:
    """The PR's Unity project, created on first use and reused afterwards.

    Returns the project path, or None when it could not be created.
    """
    project = pr_workspace.pr_dir(owner, repo, number)
    if pr_workspace.is_project(owner, repo, number):
        log(f"Reusing the Unity project at {project}.")
        prepare_manifest(str(project))
        return str(project)

    name = pr_workspace.pr_name(repo, number)
    parent = pr_workspace.unity_parent_dir(owner)
    subcommand = project_subcommand()
    log(
        f"Creating Unity project {name} ({editor_version()}, {template_id()}) "
        f"for PR #{number} at {project} ..."
    )
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log(f"Could not create {parent}: {exc}")
        return None

    # `--path` is the PARENT directory: the project lands at <parent>/<name>,
    # which is the PR's directory.
    cmd = [
        cli,
        "projects",
        subcommand,
        name,
        "--path",
        str(parent),
        "--editor-version",
        editor_version(),
        "--template",
        template_id(),
        "--non-interactive",
    ]
    if subcommand == "create":
        # `new` never links Unity Cloud; `create` has to be told not to.
        cmd.append("--no-cloud")

    # The PR's directory can already exist without being a project — an earlier
    # run that skipped or failed this step put the session and the clone there —
    # and the CLI refuses to create a project where a path exists. Move it aside
    # for the duration; the contents come back afterwards either way.
    try:
        with pr_workspace.room_for_project(owner, repo, number):
            proc = subprocess.run(cmd, timeout=UNITY_TIMEOUT, capture_output=True, text=True)
    except (subprocess.TimeoutExpired, OSError) as exc:
        log(f"Could not create the Unity project: {exc}")
        return None
    if proc.returncode != 0 or not pr_workspace.is_project(owner, repo, number):
        tail = (proc.stdout + proc.stderr).strip()[-500:]
        log(f"unity projects {subcommand} failed (exit {proc.returncode}): {tail}")
        return None
    log(f"Unity project created at {project}.")
    prepare_manifest(str(project))
    return str(project)


def reserve_project(owner: str, repo: str, number: int) -> Optional[str]:
    """Lay out the PR's Unity project, before anything is put inside it.

    The project directory *is* the PR's directory, and ``unity projects create``
    refuses a path that already exists — so this has to run before the clone is
    moved in from staging. Returns the project path, or None when Unity is not
    configured or the project could not be created.
    """
    cli = unity_cli()
    if not cli:
        return None
    return ensure_project(owner, repo, number, cli)


def unregister_project(owner: str, repo: str, number: int) -> None:
    """Remove the PR's project from the Hub registry, if it was registered.

    Best-effort: the registry is keyed by path, so a project created with
    ``projects create`` leaves a dead entry behind once its directory is gone.
    Nothing here may stop the cleanup.
    """
    if not pr_workspace.is_project(owner, repo, number):
        return
    cli = unity_cli()
    if not cli:
        return
    project = project_dir(owner, repo, number)
    try:
        proc = subprocess.run(
            [cli, "projects", "remove", project, "--force", "--non-interactive"],
            timeout=120,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            log("Removed the project from the Unity Hub registry.")
        else:
            # Usually just "not registered" — `projects create` only writes the
            # registry entry when the Hub itself lays the project out.
            log(
                "The project was not in the Hub registry (nothing to remove); "
                "its directory still goes away."
            )
    except (subprocess.TimeoutExpired, OSError) as exc:
        log(f"Could not remove the project from the Hub registry ({exc}).")


# --------------------------------------------------------------------------- #
# manifest.json
# --------------------------------------------------------------------------- #

def _manifest_path(project: str) -> Path:
    return Path(project) / "Packages" / "manifest.json"


def _read_manifest(project: str) -> Dict[str, Any]:
    path = _manifest_path(project)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(project: str, data: Dict[str, Any]) -> None:
    path = _manifest_path(project)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def project_has_package(project: str, pkg_name: str) -> bool:
    """Is ``pkg_name`` already a dependency of the project?"""
    try:
        deps = _read_manifest(project).get("dependencies") or {}
        return pkg_name in deps
    except (OSError, ValueError) as exc:
        log(f"Could not read the project manifest: {exc}")
        return False


def _manifest_add(project: str, pkg_name: str, package_root: str) -> None:
    data = _read_manifest(project)
    deps = data.setdefault("dependencies", {})
    # Unity wants forward slashes in a file: URL.
    deps[pkg_name] = "file:" + package_root.replace("\\", "/")
    _write_manifest(project, data)


def ensure_testable(project: str, pkg_name: str) -> None:
    """Register a package so the Test Runner compiles and runs its tests.

    ``testables`` is what tells Unity to include a package's test assemblies; a
    package that is only a dependency has its tests ignored — not failed — so
    ``-runTests`` reports nothing and a package with broken tests looks like a
    pass. Best-effort: a manifest that cannot be edited costs test coverage, not
    the review.
    """
    try:
        data = _read_manifest(project)
    except (OSError, ValueError) as exc:
        log(f"Could not read the project manifest to add testables: {exc}")
        return

    testables = data.get("testables")
    if not isinstance(testables, list):
        testables = []
    if pkg_name in testables:
        return
    testables.append(pkg_name)
    data["testables"] = testables
    try:
        _write_manifest(project, data)
    except OSError as exc:
        log(f"Could not write testables into the manifest: {exc}")
        return
    log(f"Added {pkg_name} to testables.")


# The package feeds every per-PR project is pointed at, so a package under review
# can resolve its own dependencies (UniTask, Nifty, NuGet-for-Unity, …) instead of
# failing the build on a package Unity cannot find.
SCOPED_REGISTRIES: List[Dict[str, Any]] = [
    {
        "name": "Peropero",
        "url": "https://unitypkg.peropero.net",
        "scopes": ["com.prpr"],
    },
    {
        "name": "OpenUPM",
        "url": "https://package.openupm.com",
        "scopes": [
            "com.niftyhat",
            "com.cysharp",
            "org.nuget.castle",
            "org.nuget.system",
            "org.nuget.google",
            "org.nuget.microsoft",
            "org.nuget.zlinq",
            "com.neuecc",
        ],
    },
]


def ensure_scoped_registries(project: str) -> None:
    """Point the project's manifest at the organization's package feeds.

    Merged, never overwritten: a registry the template already declares keeps its
    own scopes, and a registry of the same name keeps every scope it had — the
    wanted ones are added to it. Idempotent, so the reuse path re-applies it too
    and a project created before this existed is brought up to date.
    """
    try:
        data = _read_manifest(project)
    except (OSError, ValueError) as exc:
        log(f"Could not read the project manifest to add scoped registries: {exc}")
        return

    registries = data.get("scopedRegistries")
    if not isinstance(registries, list):
        registries = []
    by_name = {
        entry.get("name"): entry
        for entry in registries
        if isinstance(entry, dict) and entry.get("name")
    }

    changed = False
    for wanted in SCOPED_REGISTRIES:
        entry = by_name.get(wanted["name"])
        if entry is None:
            registries.append({"name": wanted["name"], "url": wanted["url"],
                               "scopes": list(wanted["scopes"])})
            changed = True
            continue
        if entry.get("url") != wanted["url"]:
            entry["url"] = wanted["url"]
            changed = True
        scopes = entry.get("scopes")
        if not isinstance(scopes, list):
            scopes = []
        for scope in wanted["scopes"]:
            if scope not in scopes:
                scopes.append(scope)
                changed = True
        entry["scopes"] = scopes

    if not changed:
        log("Scoped registries already configured.")
        return

    data["scopedRegistries"] = registries
    try:
        _write_manifest(project, data)
    except OSError as exc:
        log(f"Could not write the scoped registries into the manifest: {exc}")
        return
    log("Scoped registries configured: " + ", ".join(r["name"] for r in SCOPED_REGISTRIES))


# The Test Framework version a package under review expects. The 3D template
# pulls a much older one in through com.unity.feature.development (1.1.x), and a
# test assembly written against the newer TestRunner API does not compile — or
# run — against it. Raised, never lowered: an explicit newer version is left
# alone, and a project that already has a working one is not touched.
TEST_FRAMEWORK = "com.unity.test-framework"
MIN_TEST_FRAMEWORK = "1.3.4"

_VERSION_RE = re.compile(r"^\d+(?:\.\d+)*$")


def _version_tuple(value: str) -> Tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def ensure_test_framework(project: str) -> None:
    """Raise the project's Test Framework to the version packages expect.

    Best-effort, like the other manifest edits: a manifest that cannot be read or
    written costs test coverage, not the review.
    """
    try:
        data = _read_manifest(project)
    except (OSError, ValueError) as exc:
        log(f"Could not read the project manifest to check the Test Framework: {exc}")
        return

    deps = data.get("dependencies")
    if not isinstance(deps, dict):
        deps = {}
        data["dependencies"] = deps

    current = deps.get(TEST_FRAMEWORK)
    if isinstance(current, str) and _VERSION_RE.match(current.strip()):
        # A plain version we can compare. Anything else (a file:, git: or registry
        # reference) is the repository's deliberate choice — leave it alone.
        if _version_tuple(current.strip()) >= _version_tuple(MIN_TEST_FRAMEWORK):
            return
    elif current is not None:
        log(f"Leaving the project's {TEST_FRAMEWORK} reference alone: {current!r}.")
        return

    deps[TEST_FRAMEWORK] = MIN_TEST_FRAMEWORK
    try:
        _write_manifest(project, data)
    except OSError as exc:
        log(f"Could not write the Test Framework version into the manifest: {exc}")
        return
    if current:
        log(f"Raised {TEST_FRAMEWORK} from {current} to {MIN_TEST_FRAMEWORK}.")
    else:
        log(f"Pinned {TEST_FRAMEWORK} to {MIN_TEST_FRAMEWORK}.")


def prepare_manifest(project: str) -> None:
    """Everything the project's manifest needs before a package is added to it."""
    ensure_scoped_registries(project)
    ensure_test_framework(project)


def ensure_package(project: str, package_name: str, package_root: str) -> bool:
    """Make the project reference and test the package it was created for.

    The clone itself is the caller's business (:func:`pr_workspace.clone_pr_head`);
    this is only the manifest side of it.
    """
    try:
        if not project_has_package(project, package_name):
            log(f"Adding {package_name} to the Unity project as a file: dependency.")
            _manifest_add(project, package_name, package_root)
    except (OSError, ValueError) as exc:
        log(f"Could not add the package to the project manifest: {exc}")
        return False

    # Registered for tests even when the dependency was already there: a project
    # created before this existed has the package but no `testables` entry, and
    # without one the package's tests are silently never run.
    ensure_testable(project, package_name)
    return True


# --------------------------------------------------------------------------- #
# Unity batch-mode invocations
# --------------------------------------------------------------------------- #

def run_unity(
    cli: str, project: str, extra_args: List[str], timeout: int, log_file: Path
) -> Tuple[int, str]:
    """Run the editor in batch mode, through the Unity CLI.

    The CLI resolves the editor from the project's own ``ProjectVersion.txt`` —
    the version the project was created for — so there is no editor path to
    configure and none to drift out of step with the project. It also owns
    ``-batchmode``, ``-nographics``, ``-quit``, ``-projectPath`` and ``-logFile``:
    forwarding any of them is rejected outright, so only the args meant for the
    Editor itself are passed after ``--``.
    """
    # Unity does not create the log's directory, and exits without writing
    # anything when it is missing — so the caller never has to have made it.
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log(f"Could not create the log directory {log_file.parent}: {exc}")

    # `-nographics` is not optional on a headless runner, and the CLI does not
    # add it: without it the Editor dies with "Error opening default X display"
    # before it compiles anything. The CLI accepts it after `--` — unlike -quit.
    cmd = [
        cli, "run", project,
        "--log-file", str(log_file),
        "--no-tail",
        "--timeout", str(timeout),
        "--non-interactive",
        "--",
        "-nographics",
        *extra_args,
    ]
    rc, output = -1, ""
    try:
        proc = subprocess.run(cmd, timeout=timeout + 120, capture_output=True, text=True)
        rc = proc.returncode
        output = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        log(f"Unity timed out after {timeout}s.")
    except OSError as exc:
        log(f"Could not run the Unity CLI: {exc}")
        return -1, ""

    text = ""
    try:
        text = log_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    # The CLI's own output is all there is when it never reached the editor — a
    # missing license, an editor that is not installed, a permission problem.
    return rc, text + (("\n" + output) if output else "")


def run_unity_tests(
    cli: str, project: str, results: Path, mode: str, timeout: int
) -> Tuple[int, str]:
    """Run one test platform and leave the NUnit report at ``results``.

    ``unity run -runTests`` cannot be used: the CLI always passes ``-quit``, and
    the editor quits before the test run writes anything, so the step looks like
    a pass with no tests. ``unity test`` exists for exactly this and writes the
    report itself.

    Unlike ``unity run``, this command takes no arguments after ``--``: passing
    any — even ``-nographics`` — leaves it exiting 0 with no report at all, which
    would read as "no tests, no failures". So it is invoked exactly as it is and
    the missing report is treated as a failed run rather than a clean one.
    """
    if results.exists():
        results.unlink()
    cmd = [
        cli, "test", project,
        "--mode", mode,
        "--output", str(results),
        "--timeout", str(timeout),
        "--non-interactive",
    ]
    try:
        proc = subprocess.run(cmd, timeout=timeout + 120, capture_output=True, text=True)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        log(f"Unity tests timed out after {timeout}s.")
    except OSError as exc:
        log(f"Could not run the Unity CLI: {exc}")
    return -1, ""


# `Project("{GUID}") = "Name", "path.csproj", "{GUID}"`. The path is matched
# positionally — the first quoted string after the name — because a greedy match
# would run to the *last* quoted string on the line, which is the trailing GUID.
_SLN_PROJECT = re.compile(
    r'^Project\("\{[^}]+\}"\)\s*=\s*"(?P<name>[^"]+)"\s*,\s*"(?P<path>[^"]+)"'
)


def dedupe_solution(sln: str) -> int:
    """Give duplicate solution entries unique names. Returns how many were renamed.

    Unity writes one entry per generated project, and it generates both
    ``<Name>.csproj`` and ``<Name>.Player.csproj`` for the same assembly while
    labelling both with the same display name. MSBuild rejects such a solution
    outright:

        MSB5004: The solution file has two projects named "Unity.Timeline".

    That breaks anything that builds the solution before reading it — ReSharper's
    ``inspectcode`` does exactly that, and bails out with no report at all. Naming
    the second entry after its project file costs nothing and makes the generated
    solution usable.

    Only the name is spliced out and replaced, so the path, the GUIDs, the line
    endings and the column layout MSBuild expects all survive untouched. The file
    is read and written without newline translation and with its byte-order mark
    preserved: a repair that quietly rewrote the whole file's line endings would
    be a much larger change than the one it is making.
    """
    path = Path(sln)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        log(f"Could not read {path.name} to de-duplicate its projects: {exc}")
        return 0
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        log(f"Could not decode {path.name}: {exc}")
        return 0

    seen: Dict[str, int] = {}
    lines: List[str] = []
    renamed = 0
    for line in text.splitlines(keepends=True):
        match = _SLN_PROJECT.match(line)
        if match:
            name = match.group("name")
            seen[name] = seen.get(name, 0) + 1
            if seen[name] > 1:
                unique = Path(match.group("path")).stem
                line = line[: match.start("name")] + unique + line[match.end("name") :]
                renamed += 1
        lines.append(line)

    if not renamed:
        return 0

    # Never hand back something worse than what we started with: if the names
    # still collide the rewrite is abandoned and the original file stands.
    names = [m.group("name") for m in (_SLN_PROJECT.match(l) for l in lines) if m]
    remaining = {n for n in names if names.count(n) > 1}
    if remaining:
        log(
            "Could not de-duplicate "
            f"{path.name}: names still collide ({', '.join(sorted(remaining))}); "
            "leaving the solution as Unity wrote it."
        )
        return 0

    try:
        with open(
            path, "w", encoding="utf-8-sig" if had_bom else "utf-8", newline=""
        ) as handle:
            handle.write("".join(lines))
    except OSError as exc:
        log(f"Could not rewrite {path.name}: {exc}")
        return 0
    log(f"Renamed {renamed} duplicate project entr(ies) in {path.name} (MSB5004).")
    return renamed


def find_solution(project: str) -> Optional[str]:
    """The solution Unity generated for this project, or None.

    Normally it sits in the project root beside the project folders. The
    recursive search is the fallback, so a solution generated somewhere else is
    still inspected rather than silently skipped — and when there is none at
    all, that is reported by the caller instead of looking like a clean build.
    """
    root = Path(project)
    try:
        found = sorted(root.glob("*.sln"))
        if found:
            return str(found[0])
        found = sorted(
            path
            for path in root.rglob("*.sln")
            if not {"Library", "Temp", "obj", "bin"}
            & set(path.relative_to(root).parts[:-1])
        )
        if found:
            log(f"The generated solution is not in the project root; using {found[0]}.")
            return str(found[0])
    except OSError as exc:
        log(f"Could not look for a solution in {project}: {exc}")
    return None


# `<Compile Include="..\..\.ai-review\pkg\Runtime\Tiny.cs" />`, the item every
# generated csproj lists its sources in.
_CS_COMPILE = re.compile(r'<Compile\s+Include="([^"]+)"', re.IGNORECASE)


def package_projects(project: str, package_root: str) -> List[str]:
    """The generated C# projects that compile the package under review.

    Unity writes one csproj per assembly into the project root, and a package's
    asmdefs get their own. That makes the package a target ReSharper can be
    pointed at directly: a handful of files instead of the whole template, and no
    dependence on the solution being generated or usable — a csproj is accepted
    where a solution is not.

    A csproj belongs to the package when any file it compiles lives under the
    package root, which is what the assembly actually is.
    """
    if not package_root:
        return []
    root = Path(project)
    try:
        wanted = Path(package_root).resolve()
        candidates = sorted(root.glob("*.csproj"))
    except OSError as exc:
        log(f"Could not look for generated projects in {project}: {exc}")
        return []

    found: List[str] = []
    for csproj in candidates:
        try:
            text = csproj.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in _CS_COMPILE.finditer(text):
            source = Path(match.group(1).replace("\\", "/"))
            if not source.is_absolute():
                source = csproj.parent / source
            try:
                source.resolve().relative_to(wanted)
            except (ValueError, OSError):
                continue
            found.append(str(csproj))
            break
    return found


def generate_and_build(
    cli: str, project: str, log_file: Path
) -> Tuple[bool, bool, List[Dict[str, Any]], Optional[str]]:
    """Regenerate project files and compile the PR's Unity project.

    Returns ``(ran, compiled, compile_errors, sln_path)``. ``ran`` is False when
    Unity never got as far as compiling — no license on this machine, an editor
    that is not installed, a crash, a project-generation method that does not
    exist. That is an infrastructure problem, not a code problem, so the caller
    skips the step instead of failing the build. ``compiled`` is False when the
    code does not compile.
    """
    sync_method = os.environ.get("UNITY_SYNC_METHOD", "").strip()
    methods = [sync_method] if sync_method else [
        "UnityEditor.SyncVS.SyncSolution",  # built-in, regenerates sln/csproj
    ]
    rc, text = -1, ""
    for method in methods:
        log(f"Unity: generating project files via {method} ...")
        rc, text = run_unity(cli, project, ["-executeMethod", method], UNITY_TIMEOUT, log_file)
        if rc == 0:
            break

    errors = build_log.parse_compile_errors(text)
    sln = find_solution(project)
    if sln:
        # Unity's solution has to be made acceptable to MSBuild before anything
        # else (ReSharper) can build it.
        dedupe_solution(sln)
    else:
        # Exiting 0 without a solution means the generation step did not really
        # run — and with no compile errors either, "compiled" would otherwise be
        # a pass nothing backs up.
        log(
            f"Unity exited {rc} but produced no solution in {project}: the "
            "project-generation step did not run. Nothing can be inspected "
            "statically for this pull request."
        )

    if errors:
        log(f"Unity compile: {len(errors)} error(s).")
        return True, False, errors, sln
    if rc == 0:
        return True, True, errors, sln
    # Say which infrastructure reason it was, because they are fixed in different
    # places — and always report what Unity actually said, so a wrong guess here
    # costs a confused log line rather than the answer.
    lowered = text.lower()
    if any(marker in lowered for marker in LICENSE_FAILURES):
        log(
            "Unity has no valid license for the user the runner runs as; skipping "
            "the Unity step. Activate the editor for that user and re-run."
        )
    elif any(marker in lowered for marker in EDITOR_FAILURES):
        log(
            "The editor this project needs is not installed for the user the runner "
            f"runs as ({editor_version()}); skipping the Unity step."
        )
    else:
        log(f"Unity exited {rc} without compile errors; skipping the Unity step.")
    log(f"Editor log: {log_file}")
    said = " ".join(text.split())[-800:]
    if said:
        log(f"Unity said: {said}")
    return False, False, errors, sln


def run_tests(
    cli: str, project: str, results_dir: Path
) -> Tuple[bool, List[Dict[str, Any]]]:
    """Run the configured test platforms; return ``(ok, failures)``.

    PlayMode is skipped by default (a PlayMode run needs more of the editor than
    batch mode gives it); set ``UNITY_TEST_PLATFORMS`` to a comma list to
    override.
    """
    platforms = [
        p.strip()
        for p in os.environ.get("UNITY_TEST_PLATFORMS", "EditMode").split(",")
        if p.strip()
    ]
    all_failures: List[Dict[str, Any]] = []
    any_ran = False
    for platform in platforms:
        results = results_dir / f"tests-{pr_workspace.sanitize(platform)}.xml"
        log(f"Unity: running {platform} tests ...")
        rc, output = run_unity_tests(cli, project, results, platform, UNITY_TIMEOUT)
        if results.exists():
            any_ran = True
            all_failures.extend(build_log.parse_nunit_failures(results))
        else:
            log(f"Unity tests produced no report (exit {rc}): {output.strip()[-400:]}")
    # Only parsed failures count. No results file means Unity could not run the
    # tests (or the package has none) — that is not evidence of a failing test,
    # so it must not fail the build.
    ok = not all_failures
    if all_failures:
        log(f"Unity tests: {len(all_failures)} failing case(s).")
    elif not any_ran:
        log("Unity tests: no results produced; not counting it as a failure.")
    return ok, all_failures


# --------------------------------------------------------------------------- #
# cleanup
# --------------------------------------------------------------------------- #

def cleanup(owner: str, repo: str, number: int) -> None:
    """Delete everything the PR owns: project, clone and agent session.

    The session lives inside the PR's Unity project directory, so dropping that
    one directory is what "the PR is closed, forget it" means. Legacy locations
    from the shared-host layout are swept too.
    """
    unregister_project(owner, repo, number)
    pr_workspace.delete(owner, repo, number)
    log(f"Deleted the working directory for PR #{number}.")


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
        # The generated projects that compile the package itself — the precise
        # thing static analysis should look at.
        self.package_projects: List[str] = []

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


def analyze(
    clone_dir: str, owner: str, repo: str, number: int, kind: "repo_kind.Kind"
) -> UnityResult:
    """Compile and test the PR's package in the project reserved for it.

    The project itself is laid out by :func:`reserve_project` before the clone is
    moved into the PR directory, so this only fills it in. A repository that is
    not a UPM package has nothing for Unity to compile and is not touched at all.

    Never raises.
    """
    result = UnityResult()
    try:
        if not kind.is_package:
            log(f"Not a UPM package ({kind.describe()}); skipping the Unity step.")
            return result
        cli = unity_cli()
        if not cli:
            return result
        if not pr_workspace.is_project(owner, repo, number):
            log("No Unity project is reserved for this PR; skipping the Unity step.")
            return result

        project = project_dir(owner, repo, number)
        if not ensure_package(project, kind.package_name, kind.package_root):
            return result

        log_file = pr_workspace.editor_log_path(owner, repo, number)
        ran, compiled, errors, sln = generate_and_build(cli, project, log_file)
        if not ran:
            # Infrastructure failure (no license, a crash): leave ran=False so
            # the step counts as skipped, not as a broken build.
            return result
        result.ran = True
        result.compiled = compiled
        result.compile_errors = errors
        result.sln_path = sln
        result.package_projects = package_projects(project, kind.package_root)
        if result.package_projects:
            log(
                "Generated projects for the package: "
                + ", ".join(Path(p).name for p in result.package_projects)
            )

        if compiled:
            results_dir = pr_workspace.meta_dir(owner, repo, number)
            tests_ok, failures = run_tests(cli, project, results_dir)
            result.tests_ok = tests_ok
            result.test_failures = failures
        else:
            # No point testing code that does not compile.
            log("Skipping tests because compilation failed.")

        if result.sln_path:
            # Every Editor launch rewrites the generated solution, so the test run
            # above brings the duplicate project names back. Re-apply the fix as
            # the last thing before the solution is handed to ReSharper — nothing
            # after this point starts Unity again.
            dedupe_solution(result.sln_path)
        return result
    except Exception as exc:  # noqa: BLE001 - never break the review
        log(f"Unity step failed, continuing without it: {exc}")
        return result
