"""Local-file persistence for per-PR review history.

GitHub-hosted runners are ephemeral, but this workflow targets a self-hosted
runner with a persistent filesystem. We persist each pull request's accumulated
conversation transcript to a local JSON file so review history survives across
workflow runs. Files are removed automatically once the PR is closed.

The storage directory defaults to ``<tmp>/ai-code-review`` and can be overridden
with the ``REVIEW_STATE_DIR`` environment variable.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

def _resolve_state_dir() -> Path:
    value = os.environ.get("REVIEW_STATE_DIR", "").strip()
    if value:
        return Path(value)
    return Path(tempfile.gettempdir()) / "ai-code-review"


STATE_DIR = _resolve_state_dir()


def _sanitize(value: str) -> str:
    """Make an owner/repo/number safe to use as a filename component."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in value)


def state_path(owner: str, repo: str, number: int) -> Path:
    return STATE_DIR / f"{_sanitize(owner)}__{_sanitize(repo)}__{number}.json"


def load(owner: str, repo: str, number: int) -> List[Dict[str, Any]]:
    """Load stored conversation entries for a PR (empty list if none/absent)."""
    path = state_path(owner, repo, number)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("conversation", [])
    except (ValueError, OSError):
        return []


def save(owner: str, repo: str, number: int, conversation: List[Dict[str, Any]]) -> None:
    """Persist the conversation transcript for a PR to a local JSON file."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "owner": owner,
        "repo": repo,
        "number": number,
        "conversation": conversation,
    }
    state_path(owner, repo, number).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def delete(owner: str, repo: str, number: int) -> None:
    """Remove the state file for a PR (called once the PR is closed)."""
    try:
        state_path(owner, repo, number).unlink(missing_ok=True)
    except OSError:
        pass
