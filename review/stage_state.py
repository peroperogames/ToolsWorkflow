"""What the checks stage found, handed to the stages that run after it.

The review pipeline used to be one process, so the build/test results lived in
memory and the static analysis was simply called with them. Split into stages —
each its own process, each with its own timeout — that no longer holds: whatever
the static or review stage needs from the checks stage has to be written down.

Only what a *later* stage actually reads is stored. The static analysis needs the
clone, the classification and the Unity-generated projects it should inspect; the
review needs to know whether the build failed and what to tell the model about
it. Compile errors and test failures are deliberately not here: they have already
been posted as comments by the time this file is written, and a copy that nothing
reads would only be a second version of the truth to keep in step.

The file is validated on load. A stage that read a state belonging to a
different commit — or to a previous run of the same job — would act on results
that are not about this pull request's head, so the head SHA and the run identity
are both checked, and a mismatch is treated exactly like no file at all.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import repo_kind
import unity_runner

STATE_VERSION = 2

# The heading the model is shown the build status under.
BUILD_STATUS_HEADER = "## 构建与测试状态"


def build_status_context(unity_summary: str, dotnet_summary: str) -> str:
    """The build/test section handed to the model, or "" when nothing ran.

    Built from the two summaries rather than stored beside them, so there is one
    spelling of it: the checks stage puts it in the state, and a review that has
    to run the gates itself builds the same string from the same parts.
    """
    status = "\n".join(s for s in (unity_summary, dotnet_summary) if s)
    return f"{BUILD_STATUS_HEADER}\n\n{status}" if status else ""


@dataclass
class CheckState:
    """The checks stage's findings, as a later stage sees them."""

    head_sha: str = ""
    run_key: str = ""
    clone_dir: str = ""
    kind: Optional[repo_kind.Kind] = None
    blocked: bool = False
    unity_summary: str = ""
    dotnet_summary: str = ""
    unity_ran: bool = False
    unity_sln: Optional[str] = None
    unity_package_projects: List[str] = field(default_factory=list)
    static_posted: int = 0

    @property
    def extra_context(self) -> str:
        """What the review tells the model about the build and the tests."""
        return build_status_context(self.unity_summary, self.dotnet_summary)

    @classmethod
    def from_checks(
        cls,
        checks: "Any",
        head_sha: str,
        run: str,
        clone_dir: Optional[str],
    ) -> "CheckState":
        unity = checks.unity
        return cls(
            head_sha=head_sha,
            run_key=run,
            clone_dir=clone_dir or "",
            kind=checks.kind,
            blocked=bool(checks.blocked),
            unity_summary=unity.summary(),
            dotnet_summary=checks.dotnet.summary(),
            unity_ran=bool(unity.ran),
            unity_sln=unity.sln_path,
            unity_package_projects=list(unity.package_projects),
        )

    def unity_result(self) -> unity_runner.UnityResult:
        """The Unity outcome the static analysis needs, rebuilt from the state.

        Only the fields the analysis reads are carried over; the rest of the
        result describes a build that has already been reported on.
        """
        result = unity_runner.UnityResult()
        result.ran = self.unity_ran
        result.sln_path = self.unity_sln
        result.package_projects = list(self.unity_package_projects)
        return result

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": STATE_VERSION,
            "head_sha": self.head_sha,
            "run_key": self.run_key,
            "clone_dir": self.clone_dir,
            "kind": self.kind.to_dict() if self.kind else None,
            "blocked": self.blocked,
            "unity_summary": self.unity_summary,
            "dotnet_summary": self.dotnet_summary,
            "unity": {
                "ran": self.unity_ran,
                "sln_path": self.unity_sln,
                "package_projects": list(self.unity_package_projects),
            },
            "static_posted": self.static_posted,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CheckState":
        kind_data = data.get("kind")
        unity = data.get("unity") or {}
        return cls(
            head_sha=str(data.get("head_sha") or ""),
            run_key=str(data.get("run_key") or ""),
            clone_dir=str(data.get("clone_dir") or ""),
            kind=repo_kind.Kind.from_dict(kind_data) if kind_data else None,
            blocked=bool(data.get("blocked")),
            unity_summary=str(data.get("unity_summary") or ""),
            dotnet_summary=str(data.get("dotnet_summary") or ""),
            unity_ran=bool(unity.get("ran")),
            unity_sln=unity.get("sln_path") or None,
            unity_package_projects=[
                str(p) for p in (unity.get("package_projects") or []) if p
            ],
            static_posted=int(data.get("static_posted") or 0),
        )


def current_run() -> str:
    """Identifies this job run, so a previous run's state is never reused.

    ``GITHUB_RUN_ATTEMPT`` changes on a re-run, which is the case that matters:
    the same commit is checked out again and the previous file would otherwise
    look perfectly valid.
    """
    run = os.environ.get("GITHUB_RUN_ID", "").strip()
    if not run:
        return ""
    return f"{run}/{os.environ.get('GITHUB_RUN_ATTEMPT', '').strip()}"


def save(state: CheckState, path: Path) -> bool:
    """Write the state where the later stages will look for it.

    Best-effort: failing to write it costs the static analysis its targets and
    the review its build status. That is worse than nothing, but it is not a
    reason to fail a run that has already done the work.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return True
    except OSError as exc:
        print(f"Could not write {path}: {exc}", file=sys.stderr)
        return False


def load(path: Path, head_sha: str) -> Optional[CheckState]:
    """Read the state, or None when it is missing or not about this run."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        return None

    state = CheckState.from_dict(data)
    if state.head_sha and head_sha and state.head_sha != head_sha:
        return None
    wanted, got = current_run(), state.run_key
    if wanted and got and wanted != got:
        return None
    return state
