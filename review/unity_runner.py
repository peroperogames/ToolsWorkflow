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
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, Tuple

import build_log
import pr_workspace
import repo_kind
import subproc
import tool_path

UNITY_TIMEOUT = int(os.environ.get("UNITY_TIMEOUT", "1800"))  # 30 min default

# The test run gets its own deadline, ten minutes rather than the build's half
# hour: every suite seen here finishes in seconds, so a run still going after ten
# minutes is not slow — it is stuck, and the extra twenty minutes buy nothing.
# Separate from the build on purpose, so raising one does not raise the other.
UNITY_TEST_TIMEOUT = int(os.environ.get("UNITY_TEST_TIMEOUT", "600"))

# What the editor says when the run is already lost. Both phrases come from a
# Mono crash, not from a slow test: the runtime prints the dump and then does not
# exit, and the CLI waits for it until its own deadline — one pull request sat
# out its whole thirty minutes on a test host that had already died. A run that
# announces this is ended there and then, and reported as a run that produced
# nothing rather than as one that is still going.
CRASH_MARKERS = (
    "exiting early due to double fault",
    "external debugger dump",
    # A mono native crash: the editor prints this and then either exits or stops
    # responding, and the deadline would otherwise be spent waiting for a process
    # that has already died.
    "native crash reporting",
    "caught fatal signal",
)
# A Unity test that carries NUnit's `[Repeat]` is not supported by the Test
# Runner: the command it wraps calls `Execute`, which the Unity runner only
# implements as `ExecuteEnumerable`, so it throws and can take the editor down
# with it (measured on 2022.3 + UTF 1.3.4: NotImplementedException, then SIGSEGV).
REPEAT_FAILURE = "use executeenumerable"

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

# The ways Unity can be asked to write its project files. No single one exists
# everywhere: UnityEditor.SyncVS is the Visual Studio integration and quietly
# does nothing where Visual Studio is not a thing — a headless Linux runner —
# while the Rider package's entry point is a direct call into its project
# generator and ships with the template on every platform. They are tried in
# turn until files actually appear, because a zero exit code is not the same as
# having generated anything, which is exactly how a silent no-op was mistaken
# for success.
DEFAULT_SYNC_METHODS = (
    "UnityEditor.SyncVS.SyncSolution",
    "Packages.Rider.Editor.RiderScriptEditor.SyncSolution",
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

# The CLI is resolved once per run: nothing about the answer can change while the
# process lives, and every caller logging it again only lengthens the log.
_CLI: Optional[str] = None
_CLI_RESOLVED = False


def unity_cli() -> Optional[str]:
    """Path to the Unity CLI, or None when it is not installed.

    Everything Unity happens through the CLI — it lays out the project, resolves
    the editor from the project's own ``ProjectVersion.txt``, and runs the tests —
    so this is the one thing that has to be found. The editor binary is never
    looked for: hardcoding its path is what made a runner whose editor lives
    somewhere else unable to run anything at all.

    Resolved once per run and reported once, as a fact rather than a warning:
    a login shell has ~/.local/bin on its PATH and the runner's service process
    usually does not, so finding it there is the expected case, not a problem.
    When it cannot be found at all, every path that was checked is listed.
    """
    global _CLI, _CLI_RESOLVED
    if not _CLI_RESOLVED:
        _CLI = _resolve_unity_cli()
        _CLI_RESOLVED = True
    return _CLI


def _resolve_unity_cli() -> Optional[str]:
    return tool_path.find(
        "unity",
        CLI_FALLBACK_DIRS,
        override_env="UNITY_CLI",
        label="Unity CLI",
        hint=(
            "Install it for the user the runner runs as, and make sure that user's "
            "PATH has it — that user must also be able to read and execute the "
            "editor the CLI resolves. There is no Unity step without it."
        ),
    )


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
            rc, output = subproc.run(cmd, UNITY_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as exc:
        log(f"Could not create the Unity project: {exc}")
        return None
    if rc != 0 or not pr_workspace.is_project(owner, repo, number):
        log(f"unity projects {subcommand} failed (exit {rc}): {output.strip()[-500:]}")
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
        rc, _output = subproc.run(
            [cli, "projects", "remove", project, "--force", "--non-interactive"], 120
        )
        if rc == 0:
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
    """Is ``pkg_name`` already a dependency of the project?

    Only the name, which is all this is good for now that
    :func:`ensure_package` compares the path as well — a dependency pointing
    somewhere stale is present by name and useless in fact.
    """
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
            "org.nuget.moq",
        ],
    },
]


def ensure_scoped_registries(project: str) -> None:
    """Point the project's manifest at the organization's package feeds.

    The scopes are *merged*: a registry of the same name keeps every scope it
    already had and gains the ones it is missing, so a mirror or an extra scope
    somebody added survives. The URL is not merged — it is the configured one,
    which is what lets a feed that moved reach the projects that already exist
    instead of only the ones created afterwards. A repoint is logged, because it
    changes where a project resolves packages from.

    Idempotent, so the reuse path re-applies it too and a project created before
    a registry was added is brought up to date rather than left stale.
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
            log(
                f"Repointing the {wanted['name']} registry from {entry.get('url')!r} "
                f"to {wanted['url']!r}."
            )
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
# run — against it.
#
# 1.4.6 rather than 1.3.4 because 1.3.4 hangs on a `[Repeat]` over an
# `async Task` test: NUnit's repeat command calls the Unity command's synchronous
# `Execute`, which the runner only implements as `ExecuteEnumerable`, so it throws
# and the editor never finishes the suite (measured here on 2022.3.62f3: 1.3.4
# hangs with "NotImplementedException: Use ExecuteEnumerable", 1.4.6 passes the
# same test in 48s). Both require Unity 2019.4 or newer, so raising it cannot
# strand an older project.
TEST_FRAMEWORK = "com.unity.test-framework"
MIN_TEST_FRAMEWORK = "1.4.6"

# Moq, for the same reason and a different one. A package's test assemblies
# reference `Moq.dll`, which the package declares in its own asmdef's
# `precompiledReferences` — but the per-PR project starts from the 3D template's
# manifest and has never heard of it, so the reference does not resolve and the
# test assembly does not compile. It comes from OpenUPM as `org.nuget.moq`, which
# is why the scope above has to name it too.
#
# Both are raised, never lowered: an explicit newer version is left alone, and a
# project that already has a working one is not touched.
MOQ = "org.nuget.moq"
MIN_MOQ = "4.21.0"

_VERSION_RE = re.compile(r"^\d+(?:\.\d+)*$")


def _version_tuple(value: str) -> Tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def ensure_minimum_version(project: str, package: str, minimum: str, why: str) -> None:
    """Raise a dependency to ``minimum`` when it is absent or older than that.

    Shared by the two dependencies the pipeline provides for a package's tests,
    because the rule is the same one: a plain version at or above the minimum is
    left alone, and anything that is *not* a plain version — a ``file:``, ``git:``
    or registry reference — is the repository's deliberate choice and is not
    touched either.

    Best-effort, like the other manifest edits: a manifest that cannot be read or
    written costs test coverage, not the review.
    """
    try:
        data = _read_manifest(project)
    except (OSError, ValueError) as exc:
        log(f"Could not read the project manifest to check {package}: {exc}")
        return

    deps = data.get("dependencies")
    if not isinstance(deps, dict):
        deps = {}
        data["dependencies"] = deps

    current = deps.get(package)
    if isinstance(current, str) and _VERSION_RE.match(current.strip()):
        if _version_tuple(current.strip()) >= _version_tuple(minimum):
            return
    elif current is not None:
        log(f"Leaving the project's {package} reference alone: {current!r}.")
        return

    deps[package] = minimum
    try:
        _write_manifest(project, data)
    except OSError as exc:
        log(f"Could not write {package} into the manifest: {exc}")
        return
    if current:
        log(f"Raised {package} from {current} to {minimum} ({why}).")
    else:
        log(f"Added {package} at {minimum} ({why}).")


def ensure_test_framework(project: str) -> None:
    """Give the project a Test Framework new enough for the package's tests.

    The version and the reason for it live in the constants above; this line is
    what the job log shows, so it says what changed and nothing else. A changelog
    in a log line is read once and in the way of the run it is describing.
    """
    ensure_minimum_version(
        project, TEST_FRAMEWORK, MIN_TEST_FRAMEWORK, "the package's tests need it"
    )


def ensure_moq(project: str) -> None:
    """Give the project the Moq the package's test assemblies reference."""
    ensure_minimum_version(
        project, MOQ, MIN_MOQ, "the package's test assemblies reference Moq.dll"
    )


def prepare_manifest(project: str) -> None:
    """Everything the project's manifest needs before a package is added to it."""
    ensure_scoped_registries(project)
    ensure_test_framework(project)
    ensure_moq(project)


def ensure_package(project: str, package_name: str, package_root: str) -> bool:
    """Make the project reference and test the package it was created for.

    The clone itself is the caller's business (:func:`pr_workspace.clone_pr_head`);
    this is only the manifest side of it.

    The *path* is checked and not just the name, because the project outlives any
    one run while the clone it points at does not stay put: on a first review the
    clone is created in a staging directory, classified there, and moved into the
    project afterwards. A `file:` entry written from the staging path points at a
    directory that no longer exists, and Unity refuses to resolve the package —
    "Project has invalid dependencies" — which is the whole build and test step
    gone. Repairing it here also fixes a project left in that state by an earlier
    version, without anyone having to delete it.
    """
    try:
        wanted = "file:" + package_root.replace("\\", "/")
        current = (_read_manifest(project).get("dependencies") or {}).get(package_name)
        if current != wanted:
            if current:
                log(f"Repointing {package_name} from {current} to {wanted}.")
            else:
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

# Where an X server puts its socket on a Linux machine: one file per display.
X11_SOCKET_DIR = "/tmp/.X11-unix"


def running_display() -> Optional[str]:
    """The X display already running on this machine, or None.

    Unity's test run creates a graphics device when it can, and anything built on
    UI Toolkit — a ``UIDocument``, a panel, an editor window — cannot initialise
    without one, which arrives as ``No graphic device is available to initialize
    the view`` and fails the test. ``unity test`` does not pass ``-nographics``,
    so the only thing missing on a headless Linux machine is a display; Xvfb is
    commonly already there (a CI machine needs it for anything graphical), and
    its socket file is what says so.

    A ``DISPLAY`` that is already set is never overridden: the operator put it
    there, and a guess that disagrees with it is worse than no guess. Off POSIX
    there is nothing to look for.
    """
    if os.name == "nt" or os.environ.get("DISPLAY"):
        return None
    try:
        sockets = sorted(Path(X11_SOCKET_DIR).glob("X*"))
    except OSError as exc:
        log(f"Could not look for a running X display: {exc}")
        return None
    numbers = []
    for socket in sockets:
        try:
            numbers.append(int(socket.name[1:]))
        except ValueError:
            continue  # not a display socket
    return f":{min(numbers)}" if numbers else None


def usable_display() -> Optional[str]:
    """The display to run graphics work on, set or merely running.

    :func:`running_display` refuses to override a ``DISPLAY`` the operator set,
    which is right when handing a value down. This asks the other question — is
    there a display at all — because a windowed editor needs one and the two are
    equally good answers to it.
    """
    current = os.environ.get("DISPLAY", "").strip()
    if current:
        return current
    return running_display()


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
        # The editor writes its progress to the log file, not to the CLI's stdout,
        # so the deadline's heartbeat reads it from there — a compile that takes
        # twenty minutes is twenty minutes of the editor's last line.
        rc, output = subproc.run(
            cmd, timeout + 120,
            watch=str(log_file), fatal=CRASH_MARKERS, deadline=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        log(f"Unity timed out after {timeout}s.")
        output = str(getattr(exc, "output", "") or "")
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


def project_editor_version(project: str) -> str:
    """The editor version the project was made with, as Unity wrote it down."""
    path = Path(project) / "ProjectSettings" / "ProjectVersion.txt"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "m_editorversion":
            return value.strip()
    return ""


# `unity editors --json` is a process launch, and the answer cannot change
# between the two platform runs of one job.
_EDITORS_CACHE: Dict[str, Optional[str]] = {}


def _first_json_object(text: str) -> Optional[Dict[str, Any]]:
    """The first JSON object in ``text``, ignoring whatever the CLI printed first."""
    decoder = json.JSONDecoder()
    for index, char in enumerate(text or ""):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text, index)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def editor_binary(cli: str, version: str) -> Optional[str]:
    """The editor binary to drive directly, or None when the CLI cannot say.

    ``unity test`` always passes ``-batchmode``, and a batch-mode editor never
    reaches the end of a frame: a PlayMode test that waits for one hangs, and one
    that captures the screen gets no picture (measured on 2022.3 — see
    :func:`run_unity_tests_windowed`). Driving the same editor with a window
    fixes both, and the binary for that comes from the CLI's own list, so the
    version cannot drift from the project's.
    """
    if not version:
        return None
    if version in _EDITORS_CACHE:
        return _EDITORS_CACHE[version]
    resolved: Optional[str] = None
    try:
        _rc, out = subproc.run(
            [cli, "editors", "--json", "--non-interactive"], 120, echo=False
        )
        data = _first_json_object(out) or {}
        for entry in data.get("data") or []:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("version") or "") != version:
                continue
            location = str(entry.get("location") or "").strip()
            if location and Path(location).exists():
                resolved = location
                break
    except (subprocess.TimeoutExpired, OSError) as exc:
        log(f"Unity: could not list the installed editors ({exc}).")
    _EDITORS_CACHE[version] = resolved
    return resolved


def run_unity_tests_windowed(
    editor: str,
    project: str,
    results: Path,
    mode: str,
    timeout: int,
    log_path: Path,
) -> Tuple[int, str]:
    """Run one test platform in an editor with a window, leaving the report behind.

    Measured on 2022.3 against the same project and the same three tests: `yield
    return null` passes either way; `yield return new WaitForEndOfFrame()` hangs
    forever in batch mode and passes here; `ScreenCapture.CaptureScreenshotAsTexture()`
    returns a texture here and, in batch mode, fails with "was method called before
    the 'end of frame' state was reached". No flag turns the frame loop back on in
    batch mode, so the mode is the fix: a window — on a virtual display, on a
    headless machine — is what makes a rendered-frame test a test instead of a hang.
    """
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log(f"Could not create the log directory {log_path.parent}: {exc}")
    if results.exists():
        results.unlink()
    cmd = [
        editor,
        "-projectPath", project,
        "-runTests",
        "-testPlatform", mode,
        "-testResults", str(results),
        "-logFile", str(log_path),
    ]
    env = dict(os.environ)
    display = usable_display()
    if display:
        env["DISPLAY"] = display
    try:
        rc, out = subproc.run(
            cmd, timeout + 60,
            env=env,
            echo=False, preview=True, fatal=CRASH_MARKERS, deadline=timeout,
            watch=str(log_path),
            label=f"Unity {mode} tests (window)",
        )
    except subprocess.TimeoutExpired as exc:
        log(f"Unity: the windowed {mode} run timed out after {timeout}s.")
        return -1, str(getattr(exc, "output", "") or "")
    except OSError as exc:
        log(f"Unity: could not start the editor with a window: {exc}")
        return -1, ""
    text = ""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return rc, text + (("\n" + out) if out else "")


def run_unity_tests(
    cli: str, project: str, results: Path, mode: str, timeout: int
) -> Tuple[int, str]:
    """Run one test platform and leave the NUnit report at ``results``.

    ``unity run -runTests`` cannot be used: the CLI always passes ``-quit``, and
    the editor quits before the test run writes anything, so the step looks like
    a pass with no tests. ``unity test`` exists for exactly this and writes the
    report itself.

    It does not pass ``-nographics``, and it does forward arguments after ``--``
    (measured: ``unity test . -- -force-glcore`` becomes ``-batchmode -runTests
    -projectPath … -testResults … -testPlatform EditMode -force-glcore``). The
    pipeline still passes none: a test that needs a graphics device needs a
    display on the machine, not a flag, and an X server that is already running
    is handed to the run by :func:`running_display`. What the pipeline does check
    is that a report came out, so a run that never happened is a failed run
    rather than a clean one.
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
    env = dict(os.environ)
    display = running_display()
    if display:
        env["DISPLAY"] = display
        log(f"Unity: the tests run on the display {display} that is already running.")
    try:
        # Not echoed: the CLI forwards the editor's log to its stdout, which is
        # megabytes over a run that hangs — the heartbeat's last line is the
        # useful part of that, and the tail is quoted when the run fails.
        return subproc.run(
            cmd, timeout + 120,
            env=env,
            echo=False, preview=True, fatal=CRASH_MARKERS, deadline=timeout,
            label=f"Unity {mode} tests",
        )
    except subprocess.TimeoutExpired as exc:
        # What the CLI printed before it was killed is the only witness there is:
        # the editor died mid-run, so no report was written to explain anything.
        log(f"Unity tests timed out after {timeout}s.")
        return -1, str(getattr(exc, "output", "") or "")
    except OSError as exc:
        log(f"Could not run the Unity CLI: {exc}")
    return -1, ""


# `Project("{GUID}") = "Name", "path.csproj", "{GUID}"`. The path is matched
# positionally — the first quoted string after the name — because a greedy match
# would run to the *last* quoted string on the line, which is the trailing GUID.
#
# A solution *folder* looks almost the same, and is not a project: its type GUID
# is the one below and its "path" is the folder's own name. Counting those made
# `Core` under two different parents look like two projects with the same name —
# which is legal and common — and since renaming a folder to itself changes
# nothing, the repair below then gave up on a solution it could have fixed.
_SOLUTION_FOLDER = "{2150E333-8FDC-42A3-9474-1A3956D46DE8}"
_SLN_PROJECT = re.compile(
    r'^Project\("(?!'
    + re.escape(_SOLUTION_FOLDER)
    + r')\{[^}]+\}"\)\s*=\s*"(?P<name>[^"]+)"\s*,\s*"(?P<path>[^"]+)"'
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
            "leaving the solution unchanged."
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
    still inspected rather than silently skipped — and when there is none at all,
    that is reported by the caller instead of looking like a clean build.

    It does **not** descend into the PR's meta directory, because the clone lives
    there. A repository that ships its own solution used to have that solution
    mistaken for Unity's output: the search "succeeded", so the next
    project-generation method was never tried, no project files were generated at
    all, and the static analysis was pointed at the whole solution instead of at
    the package's own projects. Nothing is lost by skipping it — that solution is
    a target in its own right, from the classification.
    """
    root = Path(project)
    skipped = {"Library", "Temp", "obj", "bin", pr_workspace.META_DIRNAME}
    try:
        found = sorted(root.glob("*.sln"))
        if found:
            return str(found[0])
        found = sorted(
            path
            for path in root.rglob("*.sln")
            if not skipped & set(path.relative_to(root).parts[:-1])
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


def generated_projects(project: str) -> List[Path]:
    """Every csproj Unity generated into the project root, or an empty list.

    Only the root: that is where project generation writes them, and a nested one
    would belong to something else.
    """
    try:
        return sorted(Path(project).glob("*.csproj"))
    except OSError as exc:
        log(f"Could not look for generated projects in {project}: {exc}")
        return []


def package_assemblies(package_root: str) -> List[str]:
    """The assembly names the package declares, from its asmdef files.

    Logged next to the projects that were generated for them, because the two
    lists only mean something together: Unity names a generated project after its
    asmdef, so an assembly in one list with no counterpart in the other is how a
    package that is only *partly* inspected looks from the outside.
    """
    if not package_root:
        return []
    names: List[str] = []
    try:
        for asmdef in sorted(Path(package_root).rglob("*.asmdef")):
            try:
                name = (json.loads(asmdef.read_text(encoding="utf-8")).get("name") or "").strip()
            except (OSError, ValueError):
                continue
            if name:
                names.append(name)
    except OSError as exc:
        log(f"Could not look for asmdef files under {package_root}: {exc}")
    return sorted(names)


def _compiled_sources(csproj: Path) -> Iterator[Path]:
    """Every source file one generated project compiles, as absolute paths."""
    try:
        text = csproj.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for match in _CS_COMPILE.finditer(text):
        source = Path(match.group(1).replace("\\", "/"))
        if not source.is_absolute():
            source = csproj.parent / source
        try:
            yield source.resolve()
        except OSError:
            continue


def compiled_sources(projects: Sequence[str]) -> Set[str]:
    """Every source file the given generated projects compile."""
    found: Set[str] = set()
    for project in projects:
        for source in _compiled_sources(Path(project)):
            found.add(str(source))
    return found


def uncompiled_package_sources(
    files: Sequence[Dict[str, Any]], clone_dir: str, package_root: str, projects: Sequence[str]
) -> List[str]:
    """Changed sources under the package that no assembly compiles.

    A Unity package only compiles what an asmdef declares. A ``.cs`` file in a
    directory without one — ``Runtime/`` in a package whose only asmdef is
    ``Tests/``, say — is imported as an asset and compiled by nothing, so the
    build succeeds, the tests pass and the static analysis finds nothing: three
    green results about a file that was never looked at. The file names are
    returned in the diff's own spelling, since that is what a reader can act on.
    """
    if not package_root or not projects:
        return []
    compiled = compiled_sources(projects)
    if not compiled:
        return []
    try:
        root = Path(package_root).resolve()
        clone = Path(clone_dir).resolve() if clone_dir else root
    except OSError:
        return []

    missing: Set[str] = set()
    for entry in files:
        name = str(entry.get("filename") or "")
        parts = Path(name).parts
        # Unity ignores a directory whose name ends in `~` — Samples~ and
        # Documentation~ are for humans and imported as nothing at all.
        if not name.endswith(".cs") or any(part.endswith("~") for part in parts):
            continue
        source = (clone / name)
        try:
            source = source.resolve()
            source.relative_to(root)
        except (ValueError, OSError):
            continue  # not the package's file
        # A deleted file is not a coverage problem.
        if source.is_file() and str(source) not in compiled:
            missing.add(name)
    return sorted(missing)


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
    try:
        wanted = Path(package_root).resolve()
    except OSError as exc:
        log(f"Could not resolve the package root {package_root}: {exc}")
        return []

    found: List[str] = []
    for csproj in generated_projects(project):
        for source in _compiled_sources(csproj):
            try:
                source.relative_to(wanted)
            except ValueError:
                continue
            found.append(str(csproj))
            break
    return found


def clear_generated_projects(project: str) -> int:
    """Remove the project files Unity generated on an earlier run.

    They are regenerated below, and their absence is what makes "did this method
    write anything?" a real question: a solution left over from a previous run
    satisfies the check even when the method that was supposed to regenerate it
    did nothing at all, and the analysis then runs against a stale model — one
    that does not know about files this pull request added.
    """
    removed = 0
    try:
        stale = [*Path(project).glob("*.sln"), *Path(project).glob("*.csproj")]
    except OSError as exc:
        log(f"Could not look for generated project files in {project}: {exc}")
        return 0
    for path in stale:
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            log(f"Could not remove the stale {path.name}: {exc}")
    return removed


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
    methods = [sync_method] if sync_method else list(DEFAULT_SYNC_METHODS)
    removed = clear_generated_projects(project)
    if removed:
        log(f"Cleared {removed} project file(s) from the previous run before regenerating.")
    rc, text = -1, ""
    sln = None
    started = time.monotonic()
    for index, method in enumerate(methods, start=1):
        log(f"Unity: generating project files via {method} ...")
        rc, text = run_unity(cli, project, ["-executeMethod", method], UNITY_TIMEOUT, log_file)
        # Success is the files existing, not the exit code: the Visual Studio
        # entry point exits 0 on a machine with no Visual Studio and writes
        # nothing at all.
        sln = find_solution(project)
        if sln:
            break
        if index < len(methods):
            log(f"  {method} wrote no project files; trying the next one.")

    # The clock covers every attempt: a method that writes nothing costs a full
    # editor launch, and the second one is part of what "how long the build took"
    # means. Reported on every path below, whether it produced code or not.
    took = build_log.format_duration(time.monotonic() - started)

    if sln:
        # Unity's solution has to be made acceptable to MSBuild before anything
        # else (ReSharper) can build it.
        dedupe_solution(sln)
    else:
        # Exiting 0 without a solution means the generation step did not really
        # run — and with no compile errors either, "compiled" would otherwise be
        # a pass nothing backs up.
        log(
            f"Unity exited {rc} after {took} but produced no solution in {project}: "
            "the project-generation step did not run. Nothing can be inspected "
            "statically for this pull request."
        )
        said = " ".join(text.split())[-800:]
        if said:
            log(f"Unity said: {said}")

    errors = build_log.parse_compile_errors(text)

    if errors:
        log(f"Unity compile failed in {took}: {len(errors)} error(s).")
        for line in build_log.format_compile_errors(errors):
            log(f"  {line}")
        log(f"Editor log: {log_file}")
        return True, False, errors, sln
    if rc == 0:
        if sln:
            log(f"Unity: compiled in {took}.")
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
    log(f"Unity: no build after {took} (exit {rc}).")
    log(f"Editor log: {log_file}")
    said = " ".join(text.split())[-800:]
    if said:
        log(f"Unity said: {said}")
    return False, False, errors, sln


# Every platform that can run, runs. A package with no PlayMode tests produces no
# PlayMode cases, which costs a few seconds and proves the same thing the absence
# of a test would have; a package whose tests are mostly PlayMode produces all of
# them, which is the difference between testing and reporting that testing
# happened. Deciding from the asmdefs which ones to try is a guess that can be
# wrong in exactly the direction that hides tests.
TEST_PLATFORMS = ("EditMode", "PlayMode")


def run_tests(
    cli: str,
    project: str,
    results_dir: Path,
    result: "UnityResult",
    package_root: str = "",
) -> None:
    """Run the configured test platforms, filling in what happened on ``result``.

    Four facts, and they answer three different questions. ``tests_ok`` is "no
    failing case was read"; ``tests_reported`` is "a report was written at all";
    ``tests_broke`` is "the run exited non-zero having written nothing". A run
    that crashed or was killed by its timeout produces nothing, which is not
    evidence of a failing test — but it is not evidence of a passing one either,
    and saying "tested" for it is a lie the pull request would go on to be
    approved under.

    When nothing was reported, the run's own last lines are kept: an editor that
    hung said everything it was going to say in its final moments, and the pull
    request has to be able to read that rather than a count of zero failures. The
    whole captured output is written beside the reports, so it can be read in
    full on the runner.

    Every platform in :data:`TEST_PLATFORMS` is run, and each one reports what it
    did on its own.
    """
    platforms = list(TEST_PLATFORMS)
    # A window is what makes a rendered-frame test possible: `unity test` always
    # passes `-batchmode`, and a batch-mode editor never finishes a frame. PlayMode
    # runs in an editor with a window when one can be had; EditMode needs no frame
    # and keeps the cheaper batch route.
    editor = editor_binary(cli, project_editor_version(project))
    display = usable_display()
    for platform in platforms:
        results = results_dir / f"tests-{pr_workspace.sanitize(platform)}.xml"
        log(f"Unity: running {platform} tests ...")
        # Timed around the run itself, so the number reported is the run's and
        # not the step's — and reported on both outcomes, which is what makes a
        # suite that "got slow" visible before it becomes a timeout.
        started = time.monotonic()
        if editor and display and platform == "PlayMode":
            log(f"Unity: in an editor with a window on display {display}.")
            rc, output = run_unity_tests_windowed(
                editor, project, results, platform, UNITY_TEST_TIMEOUT,
                results_dir / f"tests-{pr_workspace.sanitize(platform)}.editor.log",
            )
            if not results.exists() and time.monotonic() - started < 120:
                # No report and no time spent: the window did not come up. Batch
                # mode is what this pipeline did before windows existed, so fall
                # back to it rather than losing the platform.
                log("Unity: the windowed run stopped early; retrying in batch mode.")
                rc, output = run_unity_tests(
                    cli, project, results, platform, UNITY_TEST_TIMEOUT
                )
        else:
            rc, output = run_unity_tests(cli, project, results, platform, UNITY_TEST_TIMEOUT)
        took = build_log.format_duration(time.monotonic() - started)
        if results.exists():
            result.tests_reported = True
            summary = build_log.parse_nunit_summary(results)
            if summary:
                result.platform_runs.append(
                    {"platform": platform, "summary": summary, "report": str(results)}
                )
            failures = build_log.parse_nunit_failures(results)
            result.test_failures.extend(failures)
            if result.platform_runs and result.platform_runs[-1]["platform"] == platform:
                result.platform_runs[-1]["skipped_cases"] = build_log.parse_nunit_skipped(
                    results
                )
            if failures:
                log(f"Unity: {platform} tests: {len(failures)} failing case(s) in {took}.")
                for line in build_log.format_test_failures(failures):
                    log(f"  {line}")
                log(f"  report: {results}")
            else:
                log(f"Unity: {platform} tests finished in {took} with no failing case.")
        else:
            log(
                f"Unity tests produced no report after {took} (exit {rc}); not "
                "counting it as a failure, and not reporting the run as tested either."
            )
            said = output.strip()[-800:]
            if said:
                log(f"Unity said: {said}")
            # What the run did say, kept for the pull request and for the file
            # beside it: the end of a hang is the whole diagnosis.
            if REPEAT_FAILURE in output.lower():
                log(
                    "  the editor failed with \"NotImplementedException: Use "
                    "ExecuteEnumerable\": a test carries NUnit's [Repeat], which the "
                    "Unity Test Runner does not support — the repeat has to be a loop "
                    "inside the test instead."
                )
            result.test_tail = build_log.tail_lines(output)
            log_path = results_dir / f"tests-{pr_workspace.sanitize(platform)}.log"
            if save_output(log_path, output):
                result.test_log_path = str(log_path)
                log(f"  full output: {log_path}")
            # A clean exit with no report is "there was nothing to run"; a
            # non-zero one is the tool saying the run failed — a crash, a hang
            # killed by the timeout — and that is worth telling the pull request.
            if rc != 0:
                result.tests_broke = True
                if not output.strip():
                    # Nothing was printed at all, so the output cannot name the
                    # test. The only way to find it is to run less of the suite:
                    # the bisection below starts from the package's test methods
                    # and confirms its last candidate on its own.
                    hung, alone = blame_hung_test(
                        cli, project, results_dir, platform, package_root
                    )
                    result.hung_test = hung or ""
                    result.hung_alone = alone
                    if not result.hung_test:
                        log(
                            f"  the {platform} run printed nothing and the hung test "
                            "could not be narrowed down; run one fixture at a time "
                            f"with `unity test . --mode {platform} --filter <fixture>`."
                        )
    # Only parsed failures count. No results file means Unity could not run the
    # tests, and that is not evidence of a failing test, so it must not fail the
    # build.
    result.tests_ok = not result.test_failures


# --------------------------------------------------------------------------- #
# Naming the test that hung
# --------------------------------------------------------------------------- #

# What one attributed run may cost. The setup is the CLI starting the editor and
# the project importing, measured at 13-20s on the runner; a single case is
# allowed BLAME_CASE_SECONDS before it counts as the one that does not finish.
BLAME_SETUP_SECONDS = 30
BLAME_CASE_SECONDS = 10
# The whole bisection, not one run: it is a diagnosis of work that already spent
# its deadline, and it must not become a second one.
BLAME_MAX_SECONDS = 900

# `[Test]`, `[UnityTest]`, `[TestCase(...)]` and `[TestCaseSource(...)]` mark a
# method as a test. `[TestFixture]` must not, and does not: the word boundary
# after `Test` is what tells them apart.
_TEST_ATTRIBUTE = re.compile(r"\[\s*(?:Unity)?Test\b")
_TESTCASE_ATTRIBUTE = re.compile(r"\[\s*TestCase(?:Source)?\b")
# `async Task` is a test signature too, and the one PeroLog used for the tests
# this search kept missing: an `IEnumerator`-and-`void`-only pattern walked past
# them, so every probe passed and the honest answer was "needs the whole suite".
_METHOD_SIGNATURE = re.compile(
    r"\b(?:IEnumerator|IEnumerator<[^>]+>|async\s+Task(?:<[^>]+>)?|Task(?:<[^>]+>)?|void)"
    r"\s+([A-Za-z_]\w*)\s*\("
)
_NAMESPACE = re.compile(r"^\s*namespace\s+([\w.]+)")
_CLASS = re.compile(r"\b(?:class|struct)\s+([A-Za-z_]\w*)")


def test_methods(package_root: str) -> List[str]:
    """The full names of the test methods in a package's sources.

    The unit is the method, because that is the smallest thing a filter can
    select and the only answer worth putting in a comment — "PlayMode tests hung"
    is what the reader already knows. Nothing here is run or compiled: the names
    are read out of the sources to give the bisection something to cut in half.

    A method is named ``Namespace.Class.Method``, and the class is whatever
    encloses the method *at that point*: nested classes are tracked by their
    braces and popped when they close. Keeping the last class name seen instead
    was wrong in exactly the case that came up — `UrlUploadTests` declares a
    nested `UploadCases`, and every test after it was reported under the nested
    name, which the runner then matched with nothing. An empty report looked like
    a test that finished, and the bisection followed it to the wrong conclusion.

    A name this misses costs one round of the search; a name it invents costs the
    answer, which is why an empty report is treated as no information at all.
    """
    if not package_root:
        return []
    root = Path(package_root)
    found: List[str] = []
    try:
        files = sorted(p for p in root.rglob("*.cs") if "~" not in p.parts)
    except OSError as exc:
        log(f"Could not read the package's sources for test names: {exc}")
        return []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        namespace = ""
        depth = 0
        # (brace depth the class body opened at, its name) — innermost last.
        scopes: List[Tuple[int, str]] = []
        closing_class: Optional[str] = None
        pending_test = False

        def remember(method: str) -> None:
            klass = scopes[-1][1] if scopes else ""
            full = ".".join(part for part in (namespace, klass, method) if part)
            if full and full not in found:
                found.append(full)

        for line in text.splitlines():
            match = _NAMESPACE.match(line)
            if match:
                namespace = match.group(1)
            match = _CLASS.search(line)
            if match:
                closing_class = match.group(1)
            attribute = _TEST_ATTRIBUTE.search(line) or _TESTCASE_ATTRIBUTE.search(line)
            if attribute:
                # The attribute usually sits on the line above its method, but
                # `[Test] public void X()` is legal and easy to write, so the rest
                # of this line is checked before waiting for the next one.
                signature = _METHOD_SIGNATURE.search(line[attribute.end():])
                pending_test = signature is None
                if signature:
                    remember(signature.group(1))
            elif pending_test:
                signature = _METHOD_SIGNATURE.search(line)
                if signature:
                    pending_test = False
                    remember(signature.group(1))
            # Braces, one at a time: a class body opens at the first `{` after its
            # declaration and closes at the `}` that takes the depth back below
            # that point.
            for char in line:
                if char == "{":
                    depth += 1
                    if closing_class:
                        scopes.append((depth, closing_class))
                        closing_class = None
                elif char == "}":
                    while scopes and scopes[-1][0] >= depth:
                        scopes.pop()
                    depth -= 1
    return found


def _filter_pattern(names: Sequence[str]) -> str:
    """A filter selecting exactly these test methods, parameterised cases included.

    The filter is a regular expression over the full test name (measured: a name
    selects one case, ``A_(One|Three)`` selects two, and a comma list selects
    nothing). Two suffixes have to be allowed for, because the sources and the
    report do not spell a name the same way: a generic fixture carries its type
    arguments in the report (``Fixture<RectMask2D>``) and not in the source, and a
    method run once per ``[TestCase]`` argument carries them in parentheses.
    """
    parts = []
    for name in names:
        _head, _, method = name.rpartition(".")
        # The method alone, with any class before it. A test declared `virtual`
        # in an abstract fixture is reported under each concrete one, so the
        # class the sources name is not the class the runner reports — matching on
        # it hid those tests from the search entirely.
        parts.append(re.escape(method))
    return r"^(?:.*\.)?(?:" + "|".join(parts) + r")(?:\(.*\))?$"


def _report_case_count(report: Path) -> int:
    """How many test cases a report holds — 0 when it holds none or is unreadable.

    A report with no cases in it is the answer to a filter that matched nothing,
    which is not the same thing as a run that finished. Confusing the two is what
    made an earlier version name a test that does not exist: the empty report
    looked like success and the search followed it.
    """
    try:
        text = report.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return text.count("<test-case")


def blame_hung_test(
    cli: str,
    project: str,
    results_dir: Path,
    platform: str,
    package_root: str,
) -> Tuple[Optional[str], bool]:
    """Bisect a run that produced no report down to the test method that hung.

    The suite said nothing at all, so the only way to name the culprit is to run
    less of it. Each round runs half of the remaining candidates with a filter on
    their names; a report with cases in it means that half finished — so the other
    half holds the test that does not — and no report means this half does. A
    single method left is confirmed on its own with BLAME_CASE_SECONDS, which is
    the run that turns a guess into the answer.

    Returns ``(name, hangs_alone)``. ``name`` is the method's full name, or —
    when every single method finishes on its own — the smallest group that did
    hang, as ``"A + B"``, with ``hangs_alone`` False. ``None`` when no list was
    available, the budget ran out, or a filter matched nothing at all (which
    means the names and the runner disagree, and a name would be a guess).
    Best-effort throughout: this runs inside a failure path.
    """
    names = test_methods(package_root)
    if not names:
        log(
            f"Unity: no test methods could be read from the package's sources, so "
            f"the {platform} run that hung cannot be attributed."
        )
        return None, False

    started = time.monotonic()
    report = results_dir / f"tests-{pr_workspace.sanitize(platform)}.blame.xml"

    def run(pattern: str, cap: int) -> Optional[bool]:
        """True when the run finished with cases, False when it hung, None when
        the filter matched nothing (no information either way)."""
        if report.exists():
            report.unlink()
        _rc, _output = _run_filtered(cli, project, report, platform, cap, pattern)
        if not report.exists():
            return False
        if _report_case_count(report) == 0:
            return None
        return True

    lo, hi = 0, len(names)
    rounds = 0
    smallest: List[str] = []
    log(f"Unity: {len(names)} test method(s) to search for the {platform} hang.")
    while hi - lo > 1:
        if time.monotonic() - started > BLAME_MAX_SECONDS:
            log("Unity: the search took its budget; the hung test stays unnamed.")
            return None, False
        mid = (lo + hi) // 2
        group = names[lo:mid]
        # A group is expected to be quick — the whole suite is seconds, roughly a
        # quarter of a second per case — so the allowance is one second per case
        # on top of the setup, never less than one case gets. A hanging group
        # spends the whole allowance; that is what makes the wrong half obvious.
        cap = BLAME_SETUP_SECONDS + max(BLAME_CASE_SECONDS, len(group))
        rounds += 1
        log(f"Unity: blame round {rounds}: {len(group)} of {hi - lo} candidate(s) ...")
        finished = run(_filter_pattern(group), cap)
        if finished is None:
            log(
                "Unity: a filter matched no test at all — the names read from the "
                "sources are not the ones the runner reports, so the search stops "
                "rather than guess."
            )
            return None, False
        if finished:
            lo = mid  # this half finished; the hang is in the other one
            continue
        hi = mid
        smallest = group

    candidate = names[lo]
    finished = run(
        _filter_pattern([candidate]),
        BLAME_SETUP_SECONDS + BLAME_CASE_SECONDS,
    )
    if finished is None:
        log(f"Unity: no test named {candidate} exists on the runner; nothing named.")
        return None, False
    if finished:
        if not smallest:
            # Every probe ran: no half of the list hangs, and neither does the
            # single method the search settled on. What hangs needs tests from
            # *both* halves (one leaves state the other trips over), which a
            # halving search cannot see — so no name is better than a name that
            # passes on its own.
            log(
                f"Unity: {candidate} finishes on its own and every probed subset did "
                "too — the hang needs the whole suite, so no single test can be "
                "named. Narrow it by hand: run the suite minus a half at a time."
            )
            return None, False
        if len(smallest) > 1:
            # The last group that hung is a half, not the answer: shrink it by
            # dropping one member at a time, keeping the group only while it still
            # hangs without that member. Bounded by the same budget as the search,
            # and skipped when the group is too big to afford.
            group = list(smallest)
            if len(group) <= 12:
                for name in list(group):
                    if len(group) <= 1:
                        break
                    if time.monotonic() - started > BLAME_MAX_SECONDS:
                        log("Unity: the search took its budget; the group stays as it was.")
                        break
                    without = [n for n in group if n != name]
                    cap = BLAME_SETUP_SECONDS + max(BLAME_CASE_SECONDS, len(without))
                    still = run(_filter_pattern(without), cap)
                    if still is False:  # hangs without it too — it is not needed
                        group = without
                    elif still is None:
                        break
            names_text = " + ".join(group)
            log(
                f"Unity: no single test hangs on its own; the smallest group that "
                f"did was {names_text} — the hang needs them together."
            )
            return names_text, False
        log(
            f"Unity: {candidate} finishes on its own and no smaller group hung; "
            "the hang needs the rest of the suite."
        )
        return candidate, False
    log(
        f"Unity: the {platform} run hangs in {candidate} — it produced no report "
        f"within {BLAME_CASE_SECONDS}s on its own."
    )
    return candidate, True


def _run_filtered(
    cli: str,
    project: str,
    report: Path,
    platform: str,
    timeout: int,
    pattern: str,
) -> Tuple[int, str]:
    """One filtered test run, quiet, with the report as the only question asked."""
    cmd = [
        cli, "test", project,
        "--mode", platform,
        "--output", str(report),
        "--timeout", str(timeout),
        "--non-interactive",
        "--filter", pattern,
    ]
    try:
        return subproc.run(
            cmd, timeout + 60,
            echo=False, preview=False, fatal=CRASH_MARKERS, deadline=timeout,
            label=f"Unity {platform} blame run",
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        log(f"Unity: blame run failed: {exc}")
        return -1, ""


def save_output(path: Path, output: str, limit: int = 2_000_000) -> bool:
    """Write what a run printed to ``path``, keeping the end of it. Best-effort.

    The end, not the beginning: a report that lists "the first 2 MB of a
    thirty-minute hang" answers a question nobody asked, and the file has to be
    readable on a runner whose disk is shared with every other pull request.
    """
    if not output.strip():
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output[-limit:], encoding="utf-8", errors="replace")
    except OSError as exc:
        log(f"Could not write {path}: {exc}")
        return False
    return True


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
        # Did the test run actually produce a report? Not the same question as
        # `tests_ok`: a run that crashed, hung until its timeout or found no tests
        # leaves `tests_ok` alone but must not be described as "tested".
        self.tests_reported = False
        # ... and did the run itself fail? A clean exit with no report is a package
        # with nothing to run; a non-zero one is the tool saying it could not.
        self.tests_broke = False
        # What a run that produced no report said before giving up, and where the
        # whole of it was written. A hang is diagnosed from its last lines, and
        # "no report" on its own is not a diagnosis.
        self.test_tail: List[str] = []
        self.test_log_path: Optional[str] = None
        # The test method a reportless run was bisected down to, when one could
        # be found — the answer the heartbeat could never give. `hung_alone` says
        # whether that method hangs on its own or only with the rest of the suite,
        # in which case the name holds the smallest group that reproduced it.
        self.hung_test: str = ""
        self.hung_alone: bool = True
        self.compile_errors: List[Dict[str, Any]] = []
        self.test_failures: List[Dict[str, Any]] = []
        self.sln_path: Optional[str] = None
        # The generated projects that compile the package itself — the precise
        # thing static analysis should look at.
        self.package_projects: List[str] = []
        # One entry per platform that produced a report: its name, the totals the
        # report carries and where it was written — the numbers the pull request's
        # summary table is built from.
        self.platform_runs: List[Dict[str, Any]] = []

    @property
    def ok(self) -> bool:
        return self.compiled and self.tests_ok

    def summary(self) -> str:
        """One line about this step, for the pull request.

        The bot speaks the review's language on the pull request, so these are
        the Chinese strings a reader there expects — and :meth:`outcome` is the
        same thing for the job log, which is written in English throughout.
        """
        if not self.ran:
            return ""
        if self.ok:
            if self.tests_broke:
                hung = ""
                if self.hung_test:
                    hung = (
                        f"（卡在 `{self.hung_test}`）"
                        if self.hung_alone
                        else f"（单独跑都过，最小的复现组合是 `{self.hung_test}`）"
                    )
                return (
                    f"⚠️ Unity: 编译通过；单元测试没有跑完{hung}，"
                    "也就没有报告，不能算通过。" + self._platform_table()
                )
            if not self.tests_reported:
                return "⚠️ Unity: 编译通过；单元测试没有产出报告，本次未真正运行。"
            return "✅ Unity: 编译通过，单元测试通过。" + self._platform_table()
        parts = []
        if not self.compiled:
            parts.append(f"编译失败（{len(self.compile_errors)} 个错误）")
        if not self.tests_ok:
            parts.append(f"{len(self.test_failures)} 个单元测试失败")
        return "🔴 Unity: " + "；".join(parts) + "。" + self._platform_table()

    def _platform_table(self) -> str:
        """The per-platform totals as a markdown table, or "" when nothing ran.

        It lives in the summary rather than beside it because the summary is what
        every reader gets — the rebuild comment, the review prompt's build status,
        the failure comment — and a table that only appears on failure is a table
        nobody sees the day the suite is green and slow.
        """
        if not self.platform_runs:
            return ""
        lines = [
            "",
            "",
            "| 平台 | 用例 | 通过 | 失败 | 跳过 | 耗时 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]

        def duration(seconds: Any) -> str:
            try:
                value = float(seconds)
            except (TypeError, ValueError):
                return "—"
            return f"{value:.1f}s" if value < 60 else f"{int(value) // 60}m {int(value) % 60}s"

        for run in self.platform_runs:
            summary = run.get("summary") or {}
            lines.append(
                f"| {run.get('platform', '?')} | {summary.get('total', 0)} "
                f"| {summary.get('passed', 0)} | {summary.get('failed', 0)} "
                f"| {summary.get('skipped', 0)} | {duration(summary.get('duration'))} |"
            )
        return "\n".join(lines)

    def outcome(self) -> str:
        """The same result for the job log.

        Every other line the pipeline writes is English, and a lone Chinese
        sentence in the middle of them reads as a mistake rather than as a
        translation. Empty when the step did not run, like :meth:`summary`.
        """
        if not self.ran:
            return ""
        if self.ok:
            if self.tests_broke:
                where = ""
                if self.hung_test:
                    where = (
                        f" (hung in {self.hung_test})"
                        if self.hung_alone
                        else f" (no single test hangs; smallest reproducing set: {self.hung_test})"
                    )
                return (
                    "Unity: compiled; the test run did not finish, so it produced "
                    f"no report{where}."
                )
            if not self.tests_reported:
                return "Unity: compiled; the test run produced no report."
            return "Unity: compiled and tested."
        parts = []
        if not self.compiled:
            parts.append(f"{len(self.compile_errors)} compile error(s)")
        if not self.tests_ok:
            parts.append(f"{len(self.test_failures)} test failure(s)")
        return "Unity: " + ", ".join(parts) + "."


def _editor_pids(project: str) -> List[int]:
    """PIDs of the editors that have this project open.

    Read from ``/proc`` because there is no portable way to ask Unity, and the
    command line is the only place the project path appears. Off POSIX this says
    nothing: the runner is Linux, and a local Windows run does not have the
    problem often enough to justify another dependency.
    """
    if os.name == "nt":
        return []
    found: List[int] = []
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        cmdline = raw.replace(b"\x00", b" ").decode("utf-8", "replace")
        if project in cmdline:
            found.append(int(entry.name))
    return found


def reap_stale_editor(project: str) -> None:
    """End the editor an earlier run left holding this project, and clear its lock.

    Every run starts by generating project files, and Unity refuses to open a
    project another editor has open:

        Error: The project at "…" is already open in a running Editor (PID 295801).

    A run killed at its deadline, a cancelled job, or somebody trying the tests by
    hand all leave that behind — and because the check happens *before* anything
    else, every later run of that pull request loses its build, its tests and its
    static analysis to a process nobody is looking at. The project is ours and
    this runs before anything of ours is started, so anything holding it is stale
    by definition.
    """
    pids = _editor_pids(project)
    if pids:
        log(f"Unity: ending editor(s) left on this project by an earlier run: {pids}.")
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and _editor_pids(project):
            time.sleep(1)
        for pid in _editor_pids(project):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        if _editor_pids(project):
            log("Unity: an editor is still holding the project; the run may fail.")
            return
    lock = Path(project) / "Temp" / "UnityLockfile"
    try:
        if lock.exists():
            lock.unlink()
            log("Unity: removed a stale UnityLockfile.")
    except OSError as exc:
        log(f"Unity: could not remove the stale lock file: {exc}")


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
        reap_stale_editor(project)
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
        # Three facts, side by side on purpose. What the package says it is, what
        # Unity generated for it, and what else was generated — because a package
        # assembly that is missing from the middle line is a package that is only
        # partly inspected, and the static analysis looks exactly the same either
        # way.
        assemblies = package_assemblies(kind.package_root)
        if assemblies:
            log("Package assemblies: " + ", ".join(assemblies))
        if result.package_projects:
            log(
                "Generated projects for the package: "
                + ", ".join(Path(p).name for p in result.package_projects)
            )
        else:
            log("No generated project compiles the package's own files.")
        others = [
            p.name
            for p in generated_projects(project)
            if str(p) not in result.package_projects
        ]
        if others:
            log("Other generated projects, not the package's: " + ", ".join(others))

        if compiled:
            results_dir = pr_workspace.meta_dir(owner, repo, number)
            run_tests(cli, project, results_dir, result, kind.package_root)
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
