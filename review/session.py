"""Per-PR agent session: an append-only message log kept on the runner.

One pull request owns one session — every message the review agent has seen or
produced (turns, assistant replies, tool calls, tool results), stored as JSONL
under a directory of its own. Later runs append to it instead of rebuilding the
whole context from GitHub, so the model keeps the files it read and the
reasoning it did, and a push sends only its own diff rather than the full one.

GitHub stays the source of truth: a missing or damaged session is rebuilt from
it, a session another run currently holds is used without persistence, and the
whole directory is removed when the PR closes. The log is an optimization, not
state the bot needs to survive.

The storage directory defaults to ``<tmp>/ai-code-review`` and can be
overridden with the ``REVIEW_STATE_DIR`` environment variable.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


def log(message: str) -> None:
    print(message, file=sys.stderr)


def _resolve_state_dir() -> Path:
    value = os.environ.get("REVIEW_STATE_DIR", "").strip()
    if value:
        return Path(value)
    return Path(tempfile.gettempdir()) / "ai-code-review"


STATE_DIR = _resolve_state_dir()


def _sanitize(value: str) -> str:
    """Make an owner/repo/number safe to use as a path component."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in value)


def session_dir(owner: str, repo: str, number: int) -> Path:
    return STATE_DIR / f"{_sanitize(owner)}__{_sanitize(repo)}__{number}"


def session_path(owner: str, repo: str, number: int) -> Path:
    return session_dir(owner, repo, number) / "session.jsonl"


# --------------------------------------------------------------------------- #
# records
# --------------------------------------------------------------------------- #

def make_record(
    role: str,
    content: str = "",
    meta: Optional[Dict[str, Any]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Build one log record from a chat message plus bookkeeping fields.

    ``extra`` carries the protocol fields (``tool_calls``, ``tool_call_id``);
    ``meta`` carries what the loop needs later — the kind of a conversation
    entry (``comment``/``review``, with ``who``/``at``), or the ``source`` of a
    turn (``open``/``push``/``request``).
    """
    record: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "content": content,
    }
    record.update({k: v for k, v in extra.items() if v})
    if meta:
        record["meta"] = meta
    return record


def to_messages(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Chat messages for a request, with the bookkeeping fields stripped.

    A torn tail — an assistant tool-call group whose results are incomplete
    (a killed job, a half-written append) — is dropped, because the API
    rejects an unmatched tool call.
    """
    messages: List[Dict[str, Any]] = []
    for record in records:
        message: Dict[str, Any] = {
            "role": record.get("role") or "user",
            "content": record.get("content") or "",
        }
        if record.get("tool_calls"):
            message["tool_calls"] = record["tool_calls"]
        if record.get("tool_call_id"):
            message["tool_call_id"] = record["tool_call_id"]
        messages.append(message)

    index = len(messages) - 1
    while index >= 0 and messages[index]["role"] == "tool":
        index -= 1
    if index >= 0 and messages[index]["role"] == "assistant" and messages[index].get("tool_calls"):
        expected = len(messages[index]["tool_calls"])
        answered = len(messages) - index - 1
        if answered < expected:
            del messages[index:]
    return messages


def entries(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The conversation entries a session has already been shown.

    Shaped like ``fetch_conversation``'s entries so the two can be merged and
    deduplicated by body exactly the way the old history file was.
    """
    out: List[Dict[str, Any]] = []
    for record in records:
        meta = record.get("meta") or {}
        if record.get("role") != "user" or not meta.get("kind"):
            continue
        out.append(
            {
                "ts": meta.get("at") or record.get("ts") or "",
                "who": meta.get("who") or "unknown",
                "kind": meta.get("kind"),
                "body": record.get("content") or "",
            }
        )
    return out


def has_bootstrap(records: List[Dict[str, Any]]) -> bool:
    """Has this session already been handed the pull request's full diff?"""
    return any((r.get("meta") or {}).get("source") == "open" for r in records)


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #

class Session:
    """Append-only write access to one PR's log (obtained through ``hold``)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, records: List[Dict[str, Any]]) -> None:
        """Append records to the log, durably (survives a job kill)."""
        records = [r for r in records if r]
        if not records:
            return
        payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
        try:
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            log(f"Warning: could not append to the session: {exc}")


@contextmanager
def hold(owner: str, repo: str, number: int) -> Iterator[Optional[Session]]:
    """Exclusive access to a PR's session for one run.

    Yields ``None`` when another run already holds it: that run works without
    persisting rather than blocking on a review that can take twenty minutes.
    """
    path = session_path(owner, repo, number)
    acquired = False
    handle = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path.parent / ".lock", "w")
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except ImportError:
            # No flock (local dev on Windows): locking is a no-op there.
            acquired = True
        except OSError:
            acquired = False
    except OSError as exc:
        log(f"Warning: could not open the session lock ({exc}).")
    if not acquired:
        log("Another run holds this PR's session; continuing without persistence.")
    try:
        yield Session(path) if acquired else None
    finally:
        if handle is not None:
            try:
                handle.close()  # releases the flock
            except OSError:
                pass


def load(owner: str, repo: str, number: int) -> List[Dict[str, Any]]:
    """Load the session's records (empty list when absent or unreadable)."""
    path = session_path(owner, repo, number)
    if not path.is_file():
        return []
    records: List[Dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue  # a torn line is skipped, not fatal
                if isinstance(record, dict) and record.get("role"):
                    records.append(record)
    except OSError as exc:
        log(f"Warning: could not read the session: {exc}")
        return []
    return records


def delete(owner: str, repo: str, number: int) -> None:
    """Remove a PR's session directory (and any legacy history file)."""
    shutil.rmtree(session_dir(owner, repo, number), ignore_errors=True)
    legacy = STATE_DIR / f"{_sanitize(owner)}__{_sanitize(repo)}__{number}.json"
    try:
        legacy.unlink(missing_ok=True)
    except OSError:
        pass
