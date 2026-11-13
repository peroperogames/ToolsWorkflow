"""Local check: the model is handed the threads already on the pull request.

AccessKing PR #3 raised the same "result collection is not released under an
exception" concern six times — CollectionPool.cs, CommandOperationAsyncExtensions.cs
twice, CommandBus.cs, CommandOperation.cs:98, then CommandOperation.Extensions.cs:57 —
and closed the sixth two minutes later. A run gets only the new push's diff, so
without this list the fifth and sixth look brand new.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main


def thread(path, line, body, resolved):
    return {
        "path": path,
        "line": line,
        "isResolved": resolved,
        "comments": {"nodes": [{"author": {"login": "perotoolsbot"},
                                "body": body, "databaseId": 1}]},
    }


THREADS = [
    thread("Core/Common/CollectionPool.cs", None,
           "这个静态 `Stack` 没有加锁，而本库公开的异步 API …", True),
    thread("Unity/Runtime/Command/Operation/CommandOperationAsyncExtensions.cs", 76,
           "`GetResultsAsync`、`WhenAllDone`、`WhenAnyDone` 三个方法在 `await` 之后才调用 "
           "`operation.ReleaseResults()`，没有 try/finally。", True),
    thread("Core/Command/Operation/CommandOperation.cs", 98,
           "结果集合释放缺少异常保护的问题在异步扩展里已提出，但根因在这个方法："
           "`ReleaseResults` 先读 `getter` 再归还。", True),
    thread("Core/Command/CommandBus/CommandBus.cs", 76,
           "`CommandOperation` 是持有池化 `ResultCollection` 的 readonly struct …", False),
]


class FakeGitHub:
    def __init__(self, threads=THREADS):
        self.threads = threads
        self.calls = 0

    def list_review_threads(self, owner, repo, number):
        self.calls += 1
        return self.threads

    def compare(self, owner, repo, before, after):
        return [{"filename": "Core/Command/Operation/CommandOperation.Extensions.cs",
                 "patch": "@@ -54,3 +54,4 @@\n }", "additions": 1, "deletions": 0}]


briefing = main.threads_briefing(FakeGitHub(), "o", "r", 3)
print(briefing)
assert "Threads already on this pull request" in briefing
assert "Do not open another thread" in briefing
assert "CommandOperation.cs:98 [resolved]" in briefing
assert "CommandBus.cs:76 [open]" in briefing
assert "CollectionPool.cs:? [resolved]" in briefing, "a thread with no line still gets a place"
# The instruction must leave room for a legitimate re-raise, or a wrong resolution
# could never be corrected.
assert "new evidence" in briefing
print("--- every thread is listed with its state")

# It reaches the turn the model is handed, after the diff.
turns = main.build_review_turns(
    FakeGitHub(), "o", "r", {"head": {"sha": "abcdef12"}}, [], {},
    [main.turn_record("old", "open", "11111111")], [], [],
    True, extra_context="BUILD OK", threads=briefing,
)
text = turns[-1]["content"]
assert "CommandOperation.Extensions.cs" in text, text[:300]
assert briefing in text and "BUILD OK" in text, text[:400]
assert text.index("BUILD OK") < text.index("Threads already on this pull request"), text[:600]
print("--- the briefing is in the turn, after the build status")

# No threads at all: no section, and no wasted words.
assert main.threads_briefing(FakeGitHub([]), "o", "r", 3) == ""
turns = main.build_review_turns(
    FakeGitHub([]), "o", "r", {"head": {"sha": "abcdef12"}}, [], {},
    [main.turn_record("old", "open", "11111111")], [], [],
    True, extra_context="BUILD OK", threads="",
)
assert "Threads already" not in turns[-1]["content"]
print("--- a pull request with no threads gets no briefing")
print("OK")
