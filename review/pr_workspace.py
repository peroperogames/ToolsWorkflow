"""One working directory per pull request.

A pull request owns exactly one directory, named ``<repo>-PR<number>`` (e.g.
``ToolsWorkflow-PR42``), and everything a review of it needs lives inside:

    <root>/<owner>/<repo>-PR<number>/
        Assets/ ProjectSettings/ Packages/ ...   the Unity project, whose folder
                                                 name *is* its Unity project name
        .ai-review/session.jsonl                 the agent session log
        .ai-review/.lock                         exclusive-access lock
        .ai-review/pkg/                          the PR head clone
        .ai-review/editor.log                    Unity's batch-mode log

The agent session and the Unity project therefore share one lifecycle: both are
created on the PR's first review, both are reused by every later review of the
same PR (the clone is ``git``-synced to the new head and the session is appended
to rather than rebuilt), and both are deleted together when the PR closes.

``.ai-review`` is dot-prefixed so Unity's asset database ignores it: the session,
the clone and the log are never imported as assets, and they cannot appear in a
build. The clone is referenced through a ``file:`` entry in the project's
``Packages/manifest.json``, which Unity resolves the same way it does any other
local package.

The owner is a path component above the per-PR directory rather than part of its
name: the leaf keeps the name the PR is known by, while two organizations that
happen to share a repository name still get separate directories.

The root defaults to ``<tmp>/ai-code-review`` and moves with the
``REVIEW_WORK_DIR`` environment variable. ``REVIEW_STATE_DIR`` is honoured as
the older name for the same setting.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple

# Holds everything about a PR that is not the Unity project itself.
META_DIRNAME = ".ai-review"

# Environment variables that move the root, newest first. Both name the same
# setting: the session and the Unity project used to have separate roots and now
# share one directory per PR.
ROOT_ENV_VARS = ("REVIEW_WORK_DIR", "REVIEW_STATE_DIR")


def work_root() -> Path:
    """The directory every per-PR directory is created under."""
    for name in ROOT_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return Path(value)
    return Path(tempfile.gettempdir()) / "ai-code-review"


def sanitize(value: str) -> str:
    """Make an owner/repo/PR value safe to use as a path component."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in str(value))


def pr_name(repo: str, number: int) -> str:
    """The per-PR directory name, e.g. ``ToolsWorkflow-PR42``.

    It is also the Unity project's name, so it must stay a valid project folder
    name: alphanumerics, ``-``, ``_`` and ``.`` only.
    """
    return f"{sanitize(repo)}-PR{int(number)}"


def owner_dir(owner: str) -> Path:
    return work_root() / sanitize(owner)


def pr_dir(owner: str, repo: str, number: int) -> Path:
    """The PR's one directory: the Unity project root and everything beside it."""
    return owner_dir(owner) / pr_name(repo, number)


def unity_parent_dir(owner: str) -> Path:
    """The directory ``unity projects create --path`` is given.

    ``--path`` takes the *parent*, and the project lands at
    ``<parent>/<name>`` — which is exactly :func:`pr_dir`.
    """
    return owner_dir(owner)


def meta_dir(owner: str, repo: str, number: int) -> Path:
    """Where the non-Unity half of a PR's state lives (inside its project)."""
    return pr_dir(owner, repo, number) / META_DIRNAME


def session_path(owner: str, repo: str, number: int) -> Path:
    return meta_dir(owner, repo, number) / "session.jsonl"


def lock_path(owner: str, repo: str, number: int) -> Path:
    return meta_dir(owner, repo, number) / ".lock"


def package_dir(owner: str, repo: str, number: int) -> Path:
    """The PR head clone the Unity project references as a ``file:`` package."""
    return meta_dir(owner, repo, number) / "pkg"


def staging_dir(owner: str, repo: str, number: int) -> Path:
    """Where the clone waits until the PR's directory is ready for it.

    The PR directory *is* the Unity project, and ``unity projects create`` refuses
    to lay a project into a path that already exists — so while a repository is
    still being identified, its clone cannot live inside the PR directory yet. It
    waits here, as a sibling, and is renamed into place once the project has been
    created (or immediately, when there is no project to create).
    """
    return owner_dir(owner) / f".{pr_name(repo, number)}.staging"


def editor_log_path(owner: str, repo: str, number: int) -> Path:
    """Unity's ``-logFile`` for this PR.

    Per PR rather than one global file, so two reviewers running at the same
    time cannot overwrite each other's log.
    """
    return meta_dir(owner, repo, number) / "editor.log"


def is_project(owner: str, repo: str, number: int) -> bool:
    """Has a Unity project already been created at this PR's directory?

    ``ProjectSettings/ProjectVersion.txt`` is what makes a folder a Unity
    project, so its presence is what tells "create it" from "reuse it" — the
    same check the Editor itself uses.
    """
    return (pr_dir(owner, repo, number) / "ProjectSettings" / "ProjectVersion.txt").is_file()


# --------------------------------------------------------------------------- #
# the PR head clone
# --------------------------------------------------------------------------- #

def log(message: str) -> None:
    print(message, file=sys.stderr)


def _run_git(args: list, cwd: Optional[str] = None, timeout: int = 300) -> Tuple[int, str]:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, timeout=timeout, capture_output=True, text=True
    )
    return proc.returncode, (proc.stdout + proc.stderr)


def _authed_url(owner: str, repo: str, token: str) -> str:
    return f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"


def clone_pr_head(
    owner: str, repo: str, number: int, head_sha: str, token: str
) -> Optional[str]:
    """The pull request's head, checked out for the duration of the run.

    Cloned on the PR's first review; every later review fetches and checks out
    the new head in the same clone, which is what makes a re-review cheap. This
    is the only thing the pipeline needs from the repository — the language
    runners and the static analysis all read it from here.

    A first review clones into the staging directory, because the PR directory is
    not free yet; a later review finds the clone already at its final home and
    syncs it there. Either way the caller ends with a path and then calls
    :func:`place_clone`. Returns None when the clone could not be obtained.
    """
    final = package_dir(owner, repo, number)
    clone_dir = final if final.exists() else staging_dir(owner, repo, number)

    if clone_dir.exists():
        log(f"Syncing the existing clone to {head_sha[:8]} ...")
        # The clone's own remote URL carries whatever token cloned it, and an App
        # token expires within the hour — so without this a later run fetches
        # with a dead credential, fails, and clones the whole repository again.
        # Reuse only pays off if the remote is re-pointed at the current token.
        _run_git(
            ["remote", "set-url", "origin", _authed_url(owner, repo, token)],
            cwd=str(clone_dir),
        )
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
        log(f"Cloning {owner}/{repo} ...")
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
    return str(clone_dir)


def place_clone(owner: str, repo: str, number: int) -> Optional[str]:
    """Move the clone from staging into the PR directory. Returns its final path.

    A rename within the same parent directory, so it costs nothing. Called once
    the Unity project has been created (when there is one) — see
    :func:`staging_dir` for why the order matters.
    """
    final = package_dir(owner, repo, number)
    staging = staging_dir(owner, repo, number)
    if final.exists():
        # Already home: a later review reuses the clone where it is.
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        return str(final)
    if not staging.exists():
        return None
    try:
        final.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging), str(final))
    except OSError as exc:
        log(f"Could not move the clone into {final}: {exc}")
        return None
    return str(final)


def stale_dirs(owner: str, repo: str, number: int):
    """Directories this PR's state can be left in outside its own.

    The staging directory the clone waits in, plus the locations older versions
    of the tool used: the session was ``<root>/<owner>__<repo>__<number>`` and the
    package clone ``<root>/ai-review-pkgs/<owner>__<repo>__<number>``. Deletion
    sweeps them all rather than leaving them on the runner forever.
    """
    root = work_root()
    key = f"{sanitize(owner)}__{sanitize(repo)}__{int(number)}"
    yield root / key
    yield root / f"{key}.json"
    yield root / "ai-review-pkgs" / key
    yield staging_dir(owner, repo, number)


def delete(owner: str, repo: str, number: int) -> None:
    """Remove the PR's directory — Unity project, session and clone together."""
    shutil.rmtree(pr_dir(owner, repo, number), ignore_errors=True)
    for stale in stale_dirs(owner, repo, number):
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
        else:
            try:
                stale.unlink(missing_ok=True)
            except OSError:
                pass
