"""Local check: read_file hands out windows, and never the same one twice.

The review loop spent 54 steps on a 5-file pull request re-reading the same files,
because read_file returned the first 8000 characters of a file and nothing else: the
part it needed was past the cut, and asking again returned the same 8000 characters.
So the window, the header that says where it ended, and the repeat answer are what
this checks.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main


class FakeGitHub:
    def __init__(self, content):
        self.content = content
        self.reads = 0

    def get_file_content(self, owner, repo, path, ref=None):
        self.reads += 1
        return self.content


def context(content):
    ctx = main.ToolContext.__new__(main.ToolContext)
    ctx.gh = FakeGitHub(content)
    ctx.owner, ctx.repo, ctx.heads = "o", "r", "abc123"
    ctx.read_windows = set()
    ctx.read_calls = 0
    return ctx


big = "\n".join(f"line {i}" for i in range(1, 601))
ctx = context(big)

first = main._tool_read_file({"path": "Core/Thing.cs"}, ctx)
head, body = first.split("\n", 1)
print("--- a 600-line file, first window:")
print("   ", head)
assert head == "Core/Thing.cs: lines 1-200 of 600 (ask again with offset=201 for the rest)", head
assert body.splitlines()[0] == "line 1" and body.splitlines()[-1] == "line 200", body[:200]

second = main._tool_read_file({"path": "Core/Thing.cs", "offset": 201}, ctx)
head2 = second.split("\n", 1)[0]
print("--- the next window:")
print("   ", head2)
assert head2 == "Core/Thing.cs: lines 201-400 of 600 (ask again with offset=401 for the rest)", head2

third = main._tool_read_file({"path": "Core/Thing.cs", "offset": 401}, ctx)
head3 = third.split("\n", 1)[0]
print("--- the last window says it is the last:")
print("   ", head3)
assert head3 == "Core/Thing.cs: lines 401-600 of 600", head3
assert third.rstrip().endswith("line 600"), third[-40:]

# The whole file is now readable — that is the fix.
print("--- a file longer than the character limit is now readable to its end")

# Asking for a window already given does not re-send it.
reads_before = ctx.gh.reads
again = main._tool_read_file({"path": "Core/Thing.cs"}, ctx)
print("--- asking for the same window again:")
print("   ", again[:120])
assert "you already have this window" in again, again
assert len(again) < 250, len(again)
assert ctx.gh.reads == reads_before + 1  # it was fetched, but not re-delivered

# A different window is still served: only the identical one is refused.
other = main._tool_read_file({"path": "Core/Thing.cs", "offset": 101}, ctx)
assert "lines 101-300" in other.split("\n", 1)[0], other[:120]
print("--- a different range is still served")

# Small files, the common case: no hint, no truncation.
small = "\n".join("x" for _ in range(12))
ctx = context(small)
out = main._tool_read_file({"path": "a.cs"}, ctx)
assert out.split("\n", 1)[0] == "a.cs: lines 1-12 of 12", out.split("\n", 1)[0]
print("--- a short file is returned whole, with no hint")

# A single enormous line still cannot blow up the context.
ctx = context("y" * 20000)
out = main._tool_read_file({"path": "minified.js"}, ctx)
assert "window cut at the character limit" in out, out[-80:]
assert len(out) <= main.MAX_READ_FILE_CHARS + 200, len(out)
print("--- one enormous line is cut at the character limit")

# An offset past the end says so instead of returning nothing.
ctx = context(small)
out = main._tool_read_file({"path": "a.cs", "offset": 99}, ctx)
assert "past its end" in out, out
print("--- an offset past the end is reported")

# Nonsense arguments do not crash the review.
ctx = context(big)
out = main._tool_read_file({"path": "Core/Thing.cs", "offset": "later", "limit": -5}, ctx)
assert out.split("\n", 1)[0].startswith("Core/Thing.cs: lines 1-200 of 600"), out[:120]
out = main._tool_read_file({"path": "Core/Thing.cs", "offset": 0, "limit": 10**9}, ctx)
assert "lines 1-200" in out.split("\n", 1)[0], out[:120]
print("--- bad arguments fall back to the defaults")

# The schema offers the two arguments it now honours.
read_tool = next(
    tool for tool in main.REVIEW_TOOLS
    if tool.get("function", {}).get("name") == "read_file"
)
props = read_tool["function"]["parameters"]["properties"]
assert set(props) == {"path", "offset", "limit"}, props
print("--- the schema declares offset and limit")

# A run only gets so many reads, and says so as the budget runs down. PeroSerde PR #6
# spent all 64 steps reading and posted nothing; the step budget alone was a wall.
ctx = context(small)
for i in range(main.MAX_READ_FILE_CALLS):
    out = main._tool_read_file({"path": f"file{i}.cs"}, ctx)
    if i + 1 == main.MAX_READ_FILE_CALLS * 3 // 4:
        assert "reads used" in out.split("\n", 1)[0], out[:120]
        print("--- the counter appears at three quarters:")
        print("   ", out.split("\n", 1)[0])

fetched = ctx.gh.reads
refused = main._tool_read_file({"path": "one-more.cs"}, ctx)
print("--- the read after the budget:")
print("   ", refused[:150])
assert "spent its" in refused and "finish" in refused, refused
assert ctx.gh.reads == fetched, "a refused read still hit the API"
print("--- a read past the budget is refused and does not hit the API")

# A repeat still does not consume the budget, so a loop cannot spend it in one file.
ctx = context(small)
main._tool_read_file({"path": "a.cs"}, ctx)
spent = ctx.read_calls
main._tool_read_file({"path": "a.cs"}, ctx)
assert ctx.read_calls == spent + 1  # counted, but answered from "you have it"
print("--- a repeat is counted but answered without the content")
print("OK")
