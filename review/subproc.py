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

Two more things are this module's job because it is the only place that knows
when a tool started and what it is saying. The tool's own output is **echoed as
it arrives** rather than printed at the end, and every quiet minute produces a
**heartbeat** — elapsed time, and the last line the tool or the watched log file
said. A compile that takes twenty minutes used to be twenty minutes of silence in
the job log, which is exactly what a hang looks like from the outside; the
heartbeat is what makes it a slow build instead.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import build_log

# How long a signalled process group gets to clean up before it is killed.
GRACE_SECONDS = 15

# How often a running tool says it is still running, once it has been quiet for
# that long. Long enough not to bury a chatty tool's own output, short enough
# that whoever is watching the job is never left guessing.
HEARTBEAT_SECONDS = 60

# How much of a watched file is read for the heartbeat: the end of an editor log
# is megabytes long, and its last line is all the heartbeat wants.
TAIL_BYTES = 4096

# How much of a tool's output is echoed before it stops being echoed. Enough for
# a compile's worth of diagnostics, and bounded because some tools answer a hang
# by dumping the editor's entire log — and GitHub truncates a step's log at a few
# megabytes, which would push out the lines that explain the hang.
ECHO_LIMIT = 256 * 1024

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


def _last_line(text: str, limit: int = 200) -> str:
    """The last non-empty line of ``text``, shortened to ``limit`` characters."""
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped[-limit:]
    return ""


def _file_tail(path: str, limit: int = 300) -> str:
    """The last thing written to ``path``, without reading the whole of it."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - TAIL_BYTES))
            data = handle.read()
    except OSError:
        return ""
    return _last_line(data.decode("utf-8", "replace"), limit)


class _Stream:
    """What a running tool has said, as it says it.

    Collected for the caller that parses it, echoed as it arrives for whoever is
    watching the job, and remembered line by line for the heartbeat that covers
    the tool's quiet stretches.

    ``echo=False`` stops the lines reaching the log — ``git`` with a token in the
    remote URL prints that URL when it cannot connect — but the heartbeat may
    still quote the last line unless ``preview`` is off too, which is what a
    command whose output may carry a secret sets. ``echo=False, preview=True``
    is the third case: a tool that narrates megabytes (``unity test`` forwards
    the editor's log) is worth a progress line every minute and not worth 30
    minutes of echoed output.

    Echoing stops after ``ECHO_LIMIT`` bytes for that same reason.
    """

    def __init__(
        self,
        echo: bool = True,
        preview: Optional[bool] = None,
        fatal: Sequence[str] = (),
    ) -> None:
        self.lines: List[str] = []
        self.echo = echo
        self.preview = echo if preview is None else preview
        self.fatal = tuple(marker.lower() for marker in fatal)
        self.fatal_hit = ""
        self.last = ""
        self.last_at = time.monotonic()
        self.echoed = 0
        self.truncated = False

    def feed(self, line: str) -> None:
        self.lines.append(line)
        stripped = line.strip()
        if not stripped:
            return
        self.last = stripped[:200]
        self.last_at = time.monotonic()
        if self.echo and not self.truncated:
            self.echoed += len(line)
            if self.echoed > ECHO_LIMIT:
                self.truncated = True
                log(
                    f"… the first {ECHO_LIMIT // 1024} KB of this tool's output is "
                    "all that is echoed; it keeps writing, and the heartbeat says "
                    "where it has got to."
                )
            else:
                log(line.rstrip())
        if self.fatal and not self.fatal_hit:
            lowered = stripped.lower()
            for marker in self.fatal:
                if marker in lowered:
                    self.fatal_hit = marker
                    break

    def text(self) -> str:
        return "".join(self.lines)


def _pump(pipe: Any, stream: _Stream) -> None:
    """Read the tool's output until the pipe closes, one line at a time."""
    try:
        for line in pipe:
            stream.feed(line)
    except (OSError, ValueError):
        # The pipe was closed under us by the kill below. What was read is kept.
        pass


def _heartbeat(
    name: str,
    stream: _Stream,
    watch: Optional[str],
    started: float,
    timeout: float,
) -> None:
    """Say that the tool is still working, and what it last said."""
    elapsed = time.monotonic() - started
    said = (_file_tail(watch) if watch else "") or (stream.last if stream.preview else "")
    line = (
        f"{name} is still running: {build_log.format_duration(elapsed)} of its "
        f"{build_log.format_duration(timeout)} deadline"
    )
    # No full stop after a quoted line: "Compiling C# scripts...." is what two
    # punctuation marks at the end of one sentence look like.
    log(f"{line} — last: {said}" if said else f"{line}.")


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


def run(
    cmd: Sequence[str],
    timeout: float,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    watch: Optional[str] = None,
    echo: bool = True,
    preview: Optional[bool] = None,
    fatal: Sequence[str] = (),
) -> Tuple[int, str]:
    """Run ``cmd`` under a deadline that ends the whole process tree.

    Returns ``(returncode, output)``, with stderr folded into stdout so a tool
    that reports on either stream is captured in one place — callers quote the
    *tail* of this when something fails. (Ordering between the two is the tool's
    own buffering, not this function's: a child that writes to a pipe gets a
    block-buffered stdout and an unbuffered stderr, exactly as before.)

    ``output`` is also echoed as it arrives, so a twenty-minute compile is twenty
    minutes of the compiler's own words rather than twenty minutes of nothing;
    ``echo=False`` turns that off for a command whose output may carry a secret,
    and ``preview=False`` keeps its last line out of the heartbeat too — which
    ``echo=False`` also does unless ``preview=True`` is passed with it, as the
    Unity test run does: not echoed, but still worth one line a minute. The echo
    stops after ``ECHO_LIMIT``.
    ``watch`` is a file the tool writes its progress to instead of its stdout —
    the editor's log — whose last line goes into the heartbeat that covers the
    quiet minutes.

    ``fatal`` is a list of phrases that mean the tool has already lost: a line
    containing one ends the run there and then, because a tool that has declared
    itself dead is not worth the rest of its deadline. The editor does exactly
    this — a Mono double fault, then no exit until the deadline kills it, which
    cost one pull request thirty minutes per review. The return code after that
    kill is an ordinary non-zero one, so the caller reports it like any other
    run that produced nothing.

    Raises ``subprocess.TimeoutExpired`` once the deadline has passed and
    everything has been killed, and ``OSError`` when the tool cannot be started
    at all — the same two failures ``subprocess.run`` reports, so callers handle
    them the same way.
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
    stream = _Stream(echo=echo, preview=preview, fatal=fatal)
    # The reader owns the pipe: the tool keeps writing while the deadline below
    # is being enforced, and blocking on both from one thread is how a pipe
    # fills up and a tool waits forever for someone to read it.
    reader = threading.Thread(target=_pump, args=(proc.stdout, stream), daemon=True)
    reader.start()

    name = _name(cmd)
    started = time.monotonic()
    deadline = started + timeout
    # A tool that can announce its own crash is polled every second, so the
    # announcement ends the run rather than waiting out a deadline it has
    # already lost. Everything else only needs waking for the heartbeat.
    poll = 1.0 if fatal else HEARTBEAT_SECONDS
    timed_out = False
    while True:
        if stream.fatal_hit:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        try:
            proc.wait(timeout=min(remaining, poll))
            break
        except subprocess.TimeoutExpired:
            # Still running: say so, unless it is already talking.
            if time.monotonic() - stream.last_at >= HEARTBEAT_SECONDS:
                _heartbeat(name, stream, watch, started, timeout)

    if stream.fatal_hit:
        log(
            f"{name} reported \"{stream.fatal_hit}\"; ending it and everything it "
            "started rather than waiting for the deadline."
        )
        _terminate(proc)
    elif timed_out:
        log(
            f"{name} did not finish within {timeout}s; ending it and everything "
            "it started."
        )
        _terminate(proc)
    # Bounded: the tool is gone, but a grandchild it left behind may still hold
    # the pipe open, and that is not this function's problem to wait for.
    reader.join(timeout=GRACE_SECONDS)
    output = stream.text()

    if timed_out:
        # Built here rather than re-raised, so the message names the program and
        # not the whole command line — a git URL carries the token.
        expired = subprocess.TimeoutExpired(_name(cmd), timeout)
        expired.output = output
        raise expired
    return proc.returncode, output
