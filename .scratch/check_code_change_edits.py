"""Local check: a code change is applied from edits, and half a change is refused.

SQLite.net PR #1: the model was asked for complete file contents, hit the 65,536-token
output ceiling twice, and answered with unterminated JSON both times. The answer is now
the size of the change; these are the properties that make that safe.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main

failures = []


def ok(msg):
    print("ok   " + msg)


def bad(msg):
    print("FAIL " + msg)
    failures.append(msg)


SOURCE = "\n".join(
    [
        "using System;",
        "",
        "public sealed class Foo",
        "{",
        "    public void A() { }",
        "    public void B() { }",
        "}",
        "",
    ]
)

# 1. A single edit lands, and nothing else in the file moves.
updated, why = main._apply_edits(
    SOURCE, [{"find": "    public void A() { }", "replace": "    public void A() => Bar();"}]
)
if updated is not None and "public void A() => Bar();" in updated and "public void B() { }" in updated:
    ok("an edit replaces exactly its own lines")
else:
    bad(f"a simple edit failed: {why!r}")

# 2. Two edits to one file apply in order.
updated, why = main._apply_edits(
    SOURCE,
    [
        {"find": "public sealed class Foo", "replace": "public sealed class Foo<T>"},
        {"find": "public void B() { }", "replace": "public void B(T value) { }"},
    ],
)
if updated and "class Foo<T>" in updated and "B(T value)" in updated:
    ok("several edits to one file apply in order")
else:
    bad(f"two edits failed: {why!r}")

# 3. Text that is not in the file is refused, not silently skipped.
updated, why = main._apply_edits(SOURCE, [{"find": "public void C()", "replace": "x"}])
if updated is None and "not in the file" in why:
    ok("an edit whose text is absent is refused")
else:
    bad(f"a missing text was accepted: {updated!r}")

# 4. Text that occurs twice is refused: changing the first of two is not the change.
updated, why = main._apply_edits(
    SOURCE, [{"find": "    public void", "replace": "    public void"}]
)
if updated is None and "appears" in why:
    ok("an ambiguous `find` is refused instead of editing the first match")
else:
    bad(f"an ambiguous find was applied: {why!r}")

# 5. A file with CRLF line endings keeps them.
crlf = SOURCE.replace("\n", "\r\n")
updated, why = main._apply_edits(crlf, [{"find": "    public void A() { }", "replace": "    public void A() { A(); }"}])
if updated is not None and "\r\n" in updated and "A(); }" in updated:
    ok("an edit to a CRLF file applies and keeps the line endings")
else:
    bad(f"a CRLF edit failed: {why!r}")

# 6. An empty edit list is refused rather than writing the file unchanged.
updated, why = main._apply_edits(SOURCE, [])
if updated is None:
    ok("an empty edit list is refused")
else:
    bad("an empty edit list produced a file")


class GitHub:
    def __init__(self, files):
        self.files = files
        self.comments = []
        self.branches = []
        self.puts = []
        self.prs = []

    patches = {}

    def list_files(self, owner, repo, number):
        return [
            {"filename": path, "patch": self.patches.get(path, "")}
            for path in self.files
        ]

    def get_file_content(self, owner, repo, path, ref=None):
        return self.files[path]

    def post_comment(self, owner, repo, number, body):
        self.comments.append(body)
        return {"id": 1}

    def create_branch(self, owner, repo, branch, base_branch=None):
        self.branches.append(branch)
        return {}

    def put_file(self, owner, repo, path, content, branch, message):
        self.puts.append((path, content))
        return {}

    def create_pr(self, owner, repo, title, head, base, body):
        self.prs.append({"title": title, "head": head})
        return {"html_url": "https://example.invalid/pr/1"}


class AI:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0
        self.prompts = []

    def chat_message(self, messages, temperature=0.3, max_tokens=None, tools=None):
        self.calls += 1
        self.prompts.append(messages[-1]["content"])
        return self.answers.pop(0)


PR = {"head": {"ref": "feature"}}


def run(ai, gh):
    return main.handle_code_change(
        ai, gh, PR, "@perotoolsbot 改一下 A 方法", "someone", "o", "r", 1, "", "perotoolsbot"
    )


# 7. The edits reach the branch, and a PR is opened.
answer = (
    '{"message": "fix A", "files": [{"path": "Foo.cs", "edits": '
    '[{"find": "    public void A() { }", "replace": "    public void A() => Bar();"}]}]}'
)
gh = GitHub({"Foo.cs": SOURCE})
ai = AI([{"content": answer, "finish_reason": "stop"}])
run(ai, gh)
if gh.puts and gh.puts[0][0] == "Foo.cs" and "A() => Bar();" in gh.puts[0][1] and gh.prs:
    ok("the edit is committed to a branch and a pull request is opened")
else:
    bad(f"puts={gh.puts!r} prs={gh.prs!r} comments={gh.comments!r}")

# 8. An edit that cannot be placed asks again, and two of them open nothing and name
#    the file.
answer = (
    '{"message": "fix A", "files": [{"path": "Foo.cs", "edits": '
    '[{"find": "not in the file", "replace": "x"}]}]}'
)
gh = GitHub({"Foo.cs": SOURCE})
ai = AI([
    {"content": answer, "finish_reason": "stop"},
    {"content": answer, "finish_reason": "stop"},
])
run(ai, gh)
if (
    ai.calls == 2
    and "could not be used" in ai.prompts[1]
    and not gh.branches
    and not gh.prs
    and any("Foo.cs" in c for c in gh.comments)
):
    ok("an edit that cannot be placed is asked again, then opens nothing and names the file")
else:
    bad(f"calls={ai.calls} branches={gh.branches!r} comments={gh.comments!r}")

# 8b. And the second answer is used when it can be applied.
second_answer = (
    '{"message": "fix A", "files": [{"path": "Foo.cs", "edits": '
    '[{"find": "    public void A() { }", "replace": "    public void A() => Bar();"}]}]}'
)
gh = GitHub({"Foo.cs": SOURCE})
ai = AI([
    {"content": answer, "finish_reason": "stop"},
    {"content": second_answer, "finish_reason": "stop"},
])
run(ai, gh)
if gh.puts and "Bar" in gh.puts[0][1] and gh.prs:
    ok("the retry after an unapplicable edit is what gets committed")
else:
    bad(f"puts={gh.puts!r} comments={gh.comments!r}")

# 8c. Whitespace the model got wrong is not a reason to give up.
answer_ws = (
    '{"message": "fix A", "files": [{"path": "Foo.cs", "edits": '
    '[{"find": "      public void A() { }   ", "replace": "    public void A() => Bar();"}]}]}'
)
gh = GitHub({"Foo.cs": SOURCE})
ai = AI([{"content": answer_ws, "finish_reason": "stop"}])
run(ai, gh)
if gh.puts and "Bar" in gh.puts[0][1] and ai.calls == 1:
    ok("an edit that differs only in whitespace applies on the first attempt")
else:
    bad(f"calls={ai.calls} puts={gh.puts!r}")

# 9. A cut-off answer is asked for again with edits, and the retry's answer is used.
first = '{"message": "x", "files": [{"path": "Foo.cs", "content": "truncated'
second = (
    '{"message": "fix A", "files": [{"path": "Foo.cs", "edits": '
    '[{"find": "    public void B() { }", "replace": "    public void B() => Baz();"}]}]}'
)
gh = GitHub({"Foo.cs": SOURCE})
ai = AI([
    {"content": first, "finish_reason": "length"},
    {"content": second, "finish_reason": "stop"},
])
run(ai, gh)
if ai.calls == 2 and gh.puts and "B() => Baz();" in gh.puts[0][1]:
    ok("a cut-off answer is retried, and the retry is applied")
else:
    bad(f"calls={ai.calls} puts={gh.puts!r}")

# 10. Two cut-off answers post the failure message and nothing else.
gh = GitHub({"Foo.cs": SOURCE})
ai = AI([
    {"content": first, "finish_reason": "length"},
    {"content": first, "finish_reason": "length"},
])
run(ai, gh)
if not gh.puts and not gh.prs and len(gh.comments) == 1 and "代码生成失败" in gh.comments[0]:
    ok("two cut-off answers post one failure comment and change nothing")
else:
    bad(f"puts={gh.puts!r} comments={gh.comments!r}")

# 11. A file too large to send whole is shown as the lines the pull request changed,
#     numbered, and the rest of it is not sent. One such file was 60,890 prompt tokens.
huge = "\n".join(f"// filler {i}" for i in range(1, 6001)) + "\npublic void A() { }\n"
patch = "@@ -6001,1 +6001,2 @@\n public void A() { }\n+    public void A() => Bar();"
text, omitted = main._code_change_context(
    [{"path": "SQLite.cs", "content": huge}],
    "改一下 SQLite.cs 的 A 方法",
    60000,
    {"SQLite.cs": patch},
)
if "```diff" in text and "6002: +" in text and "// filler 1" not in text and len(text) < 800:
    ok("a file too large to send whole is shown as its changed lines, numbered")
else:
    bad(f"text={text[:300]!r} omitted={omitted!r}")

# 12. A small file is still shown whole even when it was changed: the model needs the
#     code around the change, not only the change.
text, _ = main._code_change_context(
    [{"path": "Foo.cs", "content": SOURCE}], "改一下 Foo.cs 的 A 方法", 60000, {"Foo.cs": patch}
)
if "```diff" not in text and "public void B() { }" in text:
    ok("a small file is still sent whole")
else:
    bad(f"text={text[:300]!r}")

# 13. The budget counts what is sent, so one huge file no longer crowds out the others.
text, omitted = main._code_change_context(
    [{"path": "SQLite.cs", "content": huge}, {"path": "Test.cs", "content": SOURCE}],
    "改一下 SQLite.cs 的 A 方法",
    2000,
    {"SQLite.cs": patch},
)
if "Test.cs" in text and "public void B() { }" in text and not omitted:
    ok("a huge file costs its change, not its size, and the other files still fit")
else:
    bad(f"omitted={omitted!r} has_test={'Test.cs' in text}")

# 14. A change outside the changed lines cannot be quoted from them: the first answer
#     guesses and fails, the retry reads the whole file and places the edit.
big_body = "\n".join(f"// filler {i}" for i in range(1, 6001)) + "\npublic void A() { }\n"
big_patch = "@@ -1,2 +1,3 @@\n // filler 1\n // filler 2\n+// changed\n"
wrong = (
    '{"message": "fix A", "files": [{"path": "Big.cs", "edits": '
    '[{"find": "public void A() => Bar();", "replace": "public void A() => Qux();"}]}]}'
)
right = (
    '{"message": "fix A", "files": [{"path": "Big.cs", "edits": '
    '[{"find": "public void A() { }", "replace": "public void A() => Baz();"}]}]}'
)
gh = GitHub({"Big.cs": big_body})
gh.patches = {"Big.cs": big_patch}
ai = AI([
    {"content": wrong, "finish_reason": "stop"},
    {"content": right, "finish_reason": "stop"},
])
run(ai, gh)
if (
    ai.calls == 2
    and "```diff" in ai.prompts[0]
    and "// filler 1" in ai.prompts[1]
    and gh.puts
    and "Baz()" in gh.puts[0][1]
):
    ok("an edit outside the changed lines makes the retry read the whole file")
else:
    bad(
        f"calls={ai.calls} first_diff={'```diff' in ai.prompts[0]} "
        f"second_whole={'// filler 1' in ai.prompts[1]} puts={gh.puts!r}"
    )

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("OK")
