"""Local check: the map stage, and what it hands the agent.

A big pull request's diff is read in slices, in parallel; each worker returns findings
as data and never posts anything, a repeat is merged away, a finding for a file the
worker was not given is dropped, and the agent that posts the review is handed those
findings instead of the diff. That is the point: the diff is sent once, not once per
step.

The worker is stubbed at the client, not at `_map_slice`, so the parsing and the
validation of what a worker returns are the real ones.
"""

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


files = [
    {
        "filename": f"srcs/Rendering/File{i}.cs",
        "status": "modified",
        "additions": 200,
        "deletions": 1,
        "patch": "\n".join(f"+line {n} of file {i}" for n in range(200)),
    }
    for i in range(10)
]
pr = {"title": "feat: timeline rendering", "body": "Adds the timeline drawing framework.", "number": 36}

slices_seen = []


class FakeClient:
    def chat(self, messages, temperature=0.0, max_tokens=None):
        content = messages[-1]["content"]
        # The slice's own files are the ones with a diff section, not the file list.
        names = re.findall(r"^### (\S+) \(", content, re.MULTILINE)
        slices_seen.append(names)
        first = names[0]
        return json.dumps(
            {
                "findings": [
                    {"path": first, "quote": "line 0 of file 0", "body": f"Issue in {first}."},
                    # the same one again: the merge must drop it
                    {"path": first, "quote": "line 0 of file 0", "body": f"Issue in {first}."},
                    # a file this worker was never given: validation must drop it
                    {"path": "srcs/Outside.cs", "quote": "x", "body": "Not my slice."},
                    # no quote: nothing to anchor it to
                    {"path": first, "quote": "", "body": "A finding with no line."},
                ],
                "notes": "The change also touches the renderer registry.",
            }
        )


original_client = main._worker_client
main._worker_client = lambda ai: FakeClient()
try:
    findings, stats = main.review_file_groups(
        ai=None, pr=pr, files=files, all_files=files, threads="", max_tokens_per_slice=2000
    )
finally:
    main._worker_client = original_client

print("--- stats:", stats)
if stats["groups"] > 1:
    ok(f"the diff was cut into {stats['groups']} slices")
else:
    bad("the diff was not sliced")
if len(slices_seen) == stats["groups"]:
    ok("every slice went to a worker")
else:
    bad(f"{stats['groups']} slices but {len(slices_seen)} worker calls")
if stats["duplicates"] == stats["groups"]:
    ok("the repeated finding was merged once per slice")
else:
    bad(f"duplicates={stats['duplicates']} for {stats['groups']} slices")
if all(f["path"] != "srcs/Outside.cs" for f in findings):
    ok("a finding for a file outside the slice never reaches the agent")
else:
    bad("an out-of-slice finding survived")
if all(f["quote"] for f in findings):
    ok("a finding with no quote is dropped")
else:
    bad("a finding without a quote survived")
if len(findings) == stats["groups"]:
    ok("the agent is handed one finding per slice")
else:
    bad(f"{len(findings)} findings for {stats['groups']} slices")

block = main.findings_block(findings)
if "## Findings from the per-slice reviewers" in block and "post_inline_comment" in block:
    ok("the findings block tells the agent to post them")
else:
    bad("the findings block does not say what to do")
if findings and findings[0]["quote"] in block and findings[0]["body"] in block:
    ok("the findings block carries the quote and the body")
else:
    bad("the findings block lost a finding")

small = [{"filename": "a.cs", "patch": "+" + "x" * 400}]
big = [{"filename": "a.cs", "patch": "+" + "x" * (main.MAP_REDUCE_OVER_TOKENS * 4)}]
print(f"--- small diff: {main.diff_tokens(small)} tokens, big: {main.diff_tokens(big)} tokens")
if main.diff_tokens(small) < main.MAP_REDUCE_OVER_TOKENS <= main.diff_tokens(big):
    ok(f"the {main.MAP_REDUCE_OVER_TOKENS // 1000}k threshold separates them")
else:
    bad("the threshold does not separate a small diff from a big one")

if "No finding survived the slices" in main.findings_block([]):
    ok("an empty map says there was nothing")
else:
    bad("an empty map is ambiguous")

# A worker that fails or answers nonsense costs its slice, not the review.
class BrokenClient:
    def chat(self, messages, temperature=0.0, max_tokens=None):
        raise RuntimeError("the model fell over")


class NonsenseClient:
    def chat(self, messages, temperature=0.0, max_tokens=None):
        return "this is not JSON at all"


for label, client in (("a worker that raises", BrokenClient()), ("a worker that answers prose", NonsenseClient())):
    main._worker_client = lambda ai, c=client: c
    try:
        got, stats = main.review_file_groups(
            ai=None, pr=pr, files=files[:3], all_files=files[:3], threads="",
            max_tokens_per_slice=4000,
        )
    finally:
        main._worker_client = original_client
    if got == []:
        ok(f"{label} costs its slice and nothing else")
    else:
        bad(f"{label} produced findings out of nothing: {got}")

# The agent's turns: findings in, diff out. `files=[]` is what the caller passes, and
# it is what keeps the diff from being re-sent on every step.
class NoGitHub:
    pass


turns = main.build_review_turns(
    NoGitHub(), "o", "r", pr, [], {}, [], [], [], False,
    extra_context=main.findings_block(findings), threads="",
)
content = turns[0]["content"] if isinstance(turns[0], dict) else str(turns[0])
if "## Findings from the per-slice reviewers" in content and findings[0]["quote"] in content:
    ok("the agent's first turn carries the findings")
else:
    bad("the findings did not reach the agent's turns")
if "```diff" not in content:
    ok("the diff itself is not in that turn")
else:
    bad("the diff is still in the turn, so it is still re-sent every step")

# The slice size is its own number, not the fallback path's chunk ceiling: with the
# ceiling (131k) a 107k-token diff was one slice — a worker reading the whole thing,
# which is what the slices exist to avoid.
per_file = (107_000 * 4) // 58
big_files = [
    {"filename": f"srcs/Input/F{i}.cs", "patch": "+" + "x" * per_file} for i in range(58)
]
groups = main.chunk_files(big_files, main.MAP_SLICE_TOKENS)
sizes = [main.diff_tokens(g) // 1000 for g in groups]
print(f"--- a 107k diff: {len(groups)} slice(s) of " + ", ".join(f"{s}k" for s in sizes))
if len(groups) >= 3:
    ok(f"a 107k diff is cut into {len(groups)} slices, not one")
else:
    bad(f"a 107k diff is only {len(groups)} slice(s)")
if main.MAP_SLICE_TOKENS < main.DEFAULT_MAX_TOKENS_PER_CHUNK:
    ok("the slice size is smaller than the fallback chunk ceiling")
else:
    bad("the slice size is the chunk ceiling, which defeats the slicing")

# A worker that never answers must not hold the review open: RhythmAce-Neo #65 hung
# for 2h25m on one such call. The stage has a deadline and keeps what came back.
import threading
import time as _time


class SlowClient:
    """Fast for the first slice, then it stops answering."""

    def __init__(self):
        self.calls = 0
        self.lock = threading.Lock()

    def chat(self, messages, temperature=0.0, max_tokens=None):
        with self.lock:
            self.calls += 1
            first = self.calls == 1
        if not first:
            _time.sleep(3)
        names = re.findall(r"^### (\S+) \(", messages[-1]["content"], re.MULTILINE)
        return json.dumps(
            {"findings": [{"path": names[0], "quote": "line 0 of file 0",
                           "body": "Fast slice finding."}]}
        )


slow = SlowClient()
main._worker_client = lambda ai: slow
started = _time.monotonic()
try:
    got, stats = main.review_file_groups(
        ai=None, pr=pr, files=files, all_files=files, threads="",
        max_tokens_per_slice=2000, concurrency=4, deadline_seconds=1,
    )
finally:
    main._worker_client = original_client
elapsed = _time.monotonic() - started
print(f"--- with one stuck worker: {len(got)} finding(s) after {elapsed:.1f}s")
if elapsed < 2.5 and len(got) >= 1:
    ok("a stuck worker is abandoned at the deadline and the rest is kept")
else:
    bad(f"the deadline did not cut it short: {elapsed:.1f}s, {len(got)} finding(s)")

# The worker's client carries the read timeout; the review's own client does not.
import ai_client

probe = ai_client.AIClient("t", read_timeout=main.MAP_WORKER_TIMEOUT_SECONDS)
plain = ai_client.AIClient("t")
if probe.read_timeout == main.MAP_WORKER_TIMEOUT_SECONDS and plain.read_timeout is None:
    ok("a worker's call is bounded, the review's is not")
else:
    bad(f"read timeouts: worker={probe.read_timeout}, review={plain.read_timeout}")

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("OK")