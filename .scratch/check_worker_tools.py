"""Local check: a slice worker can read its own files, and is bounded doing it."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main

failures = []


def ok(msg):
    print("ok   " + msg)


def bad(msg):
    print("FAIL " + msg)
    failures.append(msg)


FILES = [
    {
        "filename": "srcs/Input/InputService.cs",
        "status": "modified",
        "additions": 3,
        "deletions": 1,
        "patch": "@@ -10,2 +10,5 @@\n- old line\n+public void Register(IHandler handler) { }\n+public void Unregister() { }",
    },
    {
        "filename": "srcs/Input/InputShortcut.cs",
        "status": "modified",
        "additions": 1,
        "deletions": 0,
        "patch": "+public sealed class InputShortcut { }",
    },
]
FULL_FILE = "\n".join(f"line {i} of InputService" for i in range(1, 301))
PR = {"title": "feat: input", "body": "Adds the input framework.", "head": {"sha": "abc123"}}


class FakeGitHub:
    def __init__(self):
        self.reads = []

    def get_file_content(self, owner, repo, path, ref=None):
        self.reads.append(path)
        return FULL_FILE


def call(name, **args):
    return {"id": f"c-{name}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


class ScriptedClient:
    """Replays a list of tool-call steps, then reports what it was told to."""

    def __init__(self, steps, report=None):
        self.steps = list(steps)
        self.report = report
        self.seen = []
        self.chat_calls = 0

    def chat_message(self, messages, tools=None, temperature=0.3, max_tokens=None):
        self.chat_calls += 1
        self.seen.append([m.get("role") for m in messages])
        if self.steps:
            return {"content": "", "tool_calls": self.steps.pop(0), "finish_reason": "tool_calls"}
        if self.report is not None:
            return {"content": "", "tool_calls": [call("report_findings", **self.report)],
                    "finish_reason": "tool_calls"}
        return {"content": "", "tool_calls": [], "finish_reason": "stop"}

    def chat(self, messages, temperature=0.3, max_tokens=None):
        raise AssertionError("the worker should be using chat_message when it has tools")


def run(client, gh=None):
    main._worker_client = lambda ai: client
    try:
        return main.review_file_groups(
            ai=None, pr=PR, files=FILES, all_files=FILES, threads="",
            max_tokens_per_slice=10_000, concurrency=1, deadline_seconds=30,
            gh=gh if gh is not None else FakeGitHub(), owner="o", repo="r", heads="abc123",
        )
    finally:
        main._worker_client = None if False else main._worker_client


# 1. Read, then report: the file it asked for came back, and the finding survives.
gh = FakeGitHub()
client = ScriptedClient(
    steps=[[call("read_file", path="srcs/Input/InputService.cs")]],
    report={"findings": [{"path": "srcs/Input/InputService.cs",
                          "quote": "public void Register(IHandler handler) { }",
                          "body": "Register never stores the handler."}]},
)
main._worker_client = lambda ai: client
try:
    findings, stats = main.review_file_groups(
        ai=None, pr=PR, files=FILES, all_files=FILES, threads="",
        max_tokens_per_slice=10_000, concurrency=1, deadline_seconds=30,
        gh=gh, owner="o", repo="r", heads="abc123",
    )
finally:
    main._worker_client = lambda ai: ScriptedClient([])

print("--- readings:", gh.reads)
print("--- findings:", [(f["path"], f["body"][:30]) for f in findings])
if gh.reads == ["srcs/Input/InputService.cs"] and len(findings) == 1:
    ok("a worker reads its own file and reports a finding")
else:
    bad(f"read-then-report: reads={gh.reads}, findings={findings}")

# 2. A path outside the slice is refused, and nothing is fetched for it.
gh = FakeGitHub()
client = ScriptedClient(
    steps=[[call("read_file", path="srcs/Secret/Other.cs")]],
    report={"findings": [{"path": "srcs/Input/InputService.cs",
                          "quote": "public void Register(IHandler handler) { }",
                          "body": "Still reviewed from the diff it was given."}]},
)
main._worker_client = lambda ai: client
try:
    findings, _ = main.review_file_groups(
        ai=None, pr=PR, files=FILES, all_files=FILES, threads="",
        max_tokens_per_slice=10_000, concurrency=1, deadline_seconds=30,
        gh=gh, owner="o", repo="r", heads="abc123",
    )
finally:
    main._worker_client = lambda ai: ScriptedClient([])
if gh.reads == [] and len(findings) == 1:
    ok("a worker cannot read a file outside its slice")
else:
    bad(f"out-of-slice read: reads={gh.reads}, findings={len(findings)}")

# 3. It cannot read forever: the loop stops at MAP_WORKER_STEPS and says so.
gh = FakeGitHub()
forever = ScriptedClient(steps=[[call("read_file", path="srcs/Input/InputService.cs")]] * 20)
main._worker_client = lambda ai: forever
try:
    findings, _ = main.review_file_groups(
        ai=None, pr=PR, files=FILES, all_files=FILES, threads="",
        max_tokens_per_slice=10_000, concurrency=1, deadline_seconds=60,
        gh=gh, owner="o", repo="r", heads="abc123",
    )
finally:
    main._worker_client = lambda ai: ScriptedClient([])
print(f"--- a worker that only reads: {forever.chat_calls} call(s), {len(gh.reads)} read(s)")
if forever.chat_calls == main.MAP_WORKER_STEPS and findings == []:
    ok(f"a worker is capped at {main.MAP_WORKER_STEPS} steps and reports nothing")
else:
    bad(f"the loop ran {forever.chat_calls} times")

# 4. And it cannot read past MAP_WORKER_READS: batched calls (several per step, the
# way a model asks for a few files at once) are what makes the read cap bind, since
# the step cap is smaller than the read cap.
gh = FakeGitHub()
batched = ScriptedClient(
    steps=[
        [call("read_file", path="srcs/Input/InputService.cs", offset=i * 2 + 1),
         call("read_file", path="srcs/Input/InputShortcut.cs", offset=i * 2 + 1)]
        for i in range(main.MAP_WORKER_STEPS)
    ],
)
main._worker_client = lambda ai: batched
try:
    main.review_file_groups(
        ai=None, pr=PR, files=FILES, all_files=FILES, threads="",
        max_tokens_per_slice=10_000, concurrency=1, deadline_seconds=60,
        gh=gh, owner="o", repo="r", heads="abc123",
    )
finally:
    main._worker_client = lambda ai: ScriptedClient([])
print(
    f"--- reads fetched: {len(gh.reads)} of {main.MAP_WORKER_STEPS * 2} asked in "
    f"{batched.chat_calls} step(s)"
)
if len(gh.reads) == main.MAP_WORKER_READS:
    ok(f"reads stop at {main.MAP_WORKER_READS} per slice")
else:
    bad(f"{len(gh.reads)} reads went through, expected {main.MAP_WORKER_READS}")

# 5. A report naming a file outside the slice is dropped, by name.
client = ScriptedClient(
    steps=[],
    report={"findings": [{"path": "srcs/Elsewhere.cs", "quote": "x", "body": "Not mine."},
                         {"path": "srcs/Input/InputShortcut.cs",
                          "quote": "public sealed class InputShortcut { }",
                          "body": "No test covers it."}]},
)
main._worker_client = lambda ai: client
try:
    findings, _ = main.review_file_groups(
        ai=None, pr=PR, files=FILES, all_files=FILES, threads="",
        max_tokens_per_slice=10_000, concurrency=1, deadline_seconds=30,
        gh=FakeGitHub(), owner="o", repo="r", heads="abc123",
    )
finally:
    main._worker_client = lambda ai: ScriptedClient([])
if [f["path"] for f in findings] == ["srcs/Input/InputShortcut.cs"]:
    ok("an out-of-slice finding is still dropped when reported as tool arguments")
else:
    bad(f"out-of-slice finding survived: {[f['path'] for f in findings]}")

# 6. get_file_diff is the worker's other hand: its own file, numbered, for free.
gh = FakeGitHub()
tools = main._SliceTools(gh, "o", "r", "abc123", FILES)
mine = tools.run("get_file_diff", {"path": "srcs/Input/InputService.cs"})
theirs = tools.run("get_file_diff", {"path": "srcs/Secret/Other.cs"})
print(f"--- diff head: {mine.splitlines()[0][:70]!r}")
numbered = re.search(r"^\s*10: \+public void Register", mine, re.M)
if numbered and theirs.startswith("error:"):
    ok("get_file_diff serves the slice's own file and refuses another, free of reads")
else:
    bad(f"get_file_diff: mine={mine[:80]!r}, theirs={theirs[:80]!r}")
if gh.reads == []:
    ok("get_file_diff spends no read")
else:
    bad(f"get_file_diff spent reads: {gh.reads}")


print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("OK")
