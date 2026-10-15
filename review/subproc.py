"""Running an external tool so that its deadline leaves nothing behind.

``subprocess.run(timeout=...)`` kills the process it started, which is the tool —
but not what the tool started. ``unity run`` starts the editor, ``dotnet build``
starts MSBuild and its worker nodes, ``jb inspectcode`` starts a JVM, and all of
them are grandchildren that survive the kill. On a runner that is reused across
jobs that accumulates: an editor left holding the PR's Unity project lock and its
`Temp` directory, a build server burning a core, a JVM still writing to the
report the analysis is about to read.

Measured on Linux, for a tool that starts a helper and then hangs: both versions
return at the deadline, and only one of them leaves the helper running —

    subprocess.run(timeout=3)   returned in 3.0s, helpers still running: 1
    subproc.run(..., 3)         returned in 3.0s, helpers still running: 0

So the deadline was never the problem; the orphans were. Giving the child a
session of its own and signalling the whole process group is what ends the tree:
SIGTERM first, so a tool that flushes on the way out gets the chance (the editor's
log is what the caller reads afterwards), then SIGKILL for whatever is still
standing.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import Any, Dict, Optional, Sequence, Tuple

# How long a signalled process group gets to clean up before it is killed.
GRACE_SECONDS = 15

# Windows has no SIGKILL, and no process groups to signal either.
_KILL = getattr(signal, "SIGKILL", signal.SIGTERM)

# The action runs on Linux (see the README). Windows has no process groups to
# signal, so there the child is simply killed and a tool that leaked a
# grandchild will still leave it behind — the problem this module exists for is
# a Linux one, and so is the leak.
_POSIX = os.name == "posix"


def log(message: str) -> None:
    print(message, file=sys.stderr)


def _name(cmd: Sequence[str]) -> str:
    return os.path.basename(str(cmd[0])) if cmd else "the command"


def _signal_group(proc: "subprocess.Popen[str]", sig: int) -> bool:
    """Signal the child's whole process group. False when that is not possible."""
    if not _POSIX:
        return False
    try:
        os.killpg(os.getpgid(proc.pid), sig)
        return True
    except OSError:
        # Already gone, or not ours to signal. The caller falls back.
        return False


def _terminate(proc: "subprocess.Popen[str]") -> None:
    """End the child and everything it started, without waiting forever."""
    if _POSIX:
        if _signal_group(proc, signal.SIGTERM):
            try:
                proc.wait(timeout=GRACE_SECONDS)
                return
            except subprocess.TimeoutExpired:
                pass
        _signal_group(proc, _KILL)
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=GRACE_SECONDS)
    except (subprocess.TimeoutExpired, OSError):
        pass


def _drain(proc: "subprocess.Popen[str]") -> str:
    """Whatever the tool managed to write before it died, without waiting for it."""
    try:
        output, _ = proc.communicate(timeout=5)
        return output or ""
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return ""


def run(
    cmd: Sequence[str],
    timeout: float,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> Tuple[int, str]:
    """Run ``cmd`` under a deadline that ends the whole process tree.

    Returns ``(returncode, output)``, with stderr folded into stdout so a tool
    that reports on either stream is captured in one place — callers quote the
    *tail* of this when something fails. (Ordering between the two is the tool's
    own buffering, not this function's: a child that writes to a pipe gets a
    block-buffered stdout and an unbuffered stderr, exactly as before.) Raises
    ``subprocess.TimeoutExpired`` once the deadline has passed and everything has
    been killed, and ``OSError`` when the tool cannot be started at all — the
    same two failures ``subprocess.run`` reports, so callers handle them the same
    way.
    """
    kwargs: Dict[str, Any] = {"start_new_session": True} if _POSIX else {}
    proc = subprocess.Popen(  # noqa: S603 - the commands are ours, not user input
        list(cmd),
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        **kwargs,
    )
    try:
        output, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        log(
            f"{_name(cmd)} did not finish within {timeout}s; ending it and "
            "everything it started."
        )
        _terminate(proc)
        partial = _drain(proc)
        if partial:
            exc.output = partial
        raise
    return proc.returncode, output or ""
