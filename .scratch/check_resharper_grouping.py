"""Local check: one inspection on many lines is one comment, not many threads."""

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


def candidate(path, line, quote, head, key="PossibleIncorrectDisposalOfCapturedVariable"):
    return {"path": path, "line": line, "quote": quote, "head": head, "key": key}


HEAD = "⚠️ " + main.RESHARPER_MARKER + " Captured variable is disposed by a using statement."

# Nineteen lines of the same inspection in one file: one comment, listing the lines.
many = [candidate("tests/InputTests.cs", 10 * (i + 1), f"line {10 * (i + 1)}", HEAD) for i in range(19)]
comments, collapsed = main.group_resharper_comments(many, set())
print(f"--- 19 findings -> {len(comments)} comment(s), {collapsed} folded")
print("   anchor:", comments[0]["path"], "line", comments[0]["line"])
print("   body:", comments[0]["body"].replace("\n", " | ")[:160])
if len(comments) == 1 and collapsed == 18:
    ok("the same inspection on 19 lines becomes one comment")
else:
    bad(f"grouping produced {len(comments)} comments and {collapsed} folded")
if comments[0]["line"] == 10:
    ok("it is anchored on the first affected line")
else:
    bad(f"anchored on line {comments[0]['line']}, wanted 10")
if comments[0]["body"].count("- L") == 19 and HEAD in comments[0]["body"]:
    ok("the body lists every line and keeps the ReSharper head")
else:
    bad("the body does not list the lines")

# Two different inspections in the same file stay two comments.
mixed = [
    candidate("a.cs", 5, "x", HEAD),
    candidate("a.cs", 7, "x", HEAD),
    candidate("a.cs", 9, "y", "⚠️ " + main.RESHARPER_MARKER + " Redundant type argument specification.",
              key="RedundantTypeArgumentsOfMethod"),
]
comments, collapsed = main.group_resharper_comments(mixed, set())
if len(comments) == 2:
    ok("two inspections in one file are two comments")
else:
    bad(f"mixed inspections produced {len(comments)} comments")

# A single finding keeps its old shape: exactly the head, nothing added.
one = [candidate("b.cs", 3, "x", HEAD)]
comments, collapsed = main.group_resharper_comments(one, set())
if comments and comments[0]["body"] == HEAD and collapsed == 0:
    ok("a single finding posts as it always did")
else:
    bad(f"a single finding changed shape: {comments}")

# A long group is capped, and says how many are not listed.
long_group = [candidate("c.cs", i + 1, f"q{i}", HEAD) for i in range(40)]
comments, collapsed = main.group_resharper_comments(long_group, set())
body = comments[0]["body"]
if body.count("- L") == main.RESHARPER_GROUP_LIST_LIMIT and "另 20 处" in body:
    ok(f"the list is capped at {main.RESHARPER_GROUP_LIST_LIMIT} with a count of the rest")
else:
    bad(f"the capped list reads: {body[-80:]}")

# An open thread from an earlier push already says it for this file: not repeated.
already = {("tests/InputTests.cs", main._normalized(HEAD))}
comments, collapsed = main.group_resharper_comments(
    [candidate("tests/InputTests.cs", i + 1, f"q{i}", HEAD) for i in range(3)], already
)
if comments == []:
    ok("a group already raised on that file is not raised again")
else:
    bad(f"a raised group was repeated: {comments}")

# ... but the same inspection on a different file is a different problem.
comments, collapsed = main.group_resharper_comments(
    [candidate("other.cs", i + 1, f"q{i}", HEAD) for i in range(3)], already
)
if len(comments) == 1:
    ok("the same inspection on another file is still reported")
else:
    bad("another file's group was suppressed by the first file's thread")

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("OK")
