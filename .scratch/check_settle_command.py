"""Local check: the `settle` command judges the threads and approves — and says why."""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main

posted = []
settle_calls = []

THREAD = {
    "id": "PRRT_1",
    "path": "AndroidProject~/.project",
    "line": 12,
    "isResolved": False,
    "comments": {"nodes": [{"author": {"login": "perotoolsbot[bot]"},
                            "body": "这个文件不该提交", "databaseId": 9}]},
}
THREAD_BODY = "这个文件不该提交"


class FakeGitHub:
    def __init__(self, threads=()):
        self.threads = list(threads)

    def list_review_threads(self, owner, repo, number):
        return self.threads

    def list_files(self, owner, repo, number):
        return [
            {"filename": THREAD["path"], "patch": "@@ -1 +1 @@\n-a\n+b"},
            {"filename": "Other/Unrelated.cs", "patch": "@@ -1 +1 @@\n-x\n+y"},
        ]

    def post_comment(self, owner, repo, number, body):
        posted.append(body)
        return {"id": 1}

    def post_inline_comment(self, *args, **kwargs):
        raise AssertionError("settle must not post an inline comment")


config = types.SimpleNamespace(dry_run=False, language="cn")
ctx = main.CommandContext(
    ai=None, gh=FakeGitHub(), pr={"head": {"sha": "abc123"}}, author="someone",
    owner="o", repo="r", number=3, config=config, system_prompt="",
    conversation="", bot_login="perotoolsbot[bot]", records=[], comment_records=[],
)
command = main.parse_command("@perotoolsbot settle", "perotoolsbot[bot]")


def run(before, after, outcome):
    posted.clear()
    settle_calls.clear()
    counts = iter([before, after])
    main.unresolved_bot_thread_count = lambda gh, owner, repo, number: next(counts)
    main.settle_threads_and_approve = lambda *a, **k: settle_calls.append(k) or outcome
    code = main.handle_settle_command(ctx, command)
    assert code == 0
    assert len(settle_calls) == 1, "the threads must be judged exactly once"
    assert "skip_ids" not in settle_calls[0], "nothing of this run's own to skip"
    diff_files = settle_calls[0].get("diff_files")
    if ctx.gh.threads:
        assert diff_files and [f["filename"] for f in diff_files] == [THREAD["path"]], (
            "the decider must see the code of the file the thread is about, and only it",
            diff_files,
        )
    else:
        assert diff_files is None, diff_files
    return posted[0]


def run_with_threads(before, after, outcome):
    ctx.gh = FakeGitHub([THREAD])
    return run(before, after, outcome)


# The command itself: recognised without the model, and it asks for no build.
assert command and command.name == "settle", command
assert main.COMMAND_BY_NAME["settle"].stages == frozenset(), "settle must not run the gates"
payload = {"comment": {"body": "@perotoolsbot settle"}}
assert main._wanted_stages("issue_comment", payload) == frozenset(), "the checks stage must stand down"

body = run_with_threads(3, 0, main.SettleOutcome(resolved=3, approved=True))
print("--- all threads resolved, approved")
print(body)
assert body == "未解决线程 3 → 0，已 approve ✅", body
# The result, and nothing about what the command is for: whoever reads it just
# asked for it.
assert "不新建评论" not in body and "重新检查评论线程" not in body, body

body = run_with_threads(38, 0, main.SettleOutcome(resolved=38, approved=False))
print("--- all threads resolved, approval not submitted")
print(body)
assert "38 → 0" in body and "approve 未提交" in body, body

# The reason a thread stays open is the whole point: before this, the comment was
# "未解决线程 1 → 1，暂不 approve。" and nothing else.
body = run_with_threads(
    1, 1,
    main.SettleOutcome(open=[{
        "path": THREAD["path"], "line": 12,
        "reason": "新提交没有改动这个文件，构建产物仍然会被提交。",
        "body": THREAD_BODY,
    }]),
)
print("--- one thread left: the count only")
print(body)
assert body == "未解决线程 1 → 1，暂不 approve。", body
assert "AndroidProject" not in body, "the reason belongs in the thread, not in this comment"

# No reason from the decider: the thread's own opening line, said plainly.
body = run_with_threads(
    2, 2,
    main.SettleOutcome(open=[{
        "path": THREAD["path"], "line": None, "reason": "", "body": THREAD_BODY,
    }]),
)
print("--- two threads left: still the count only")
print(body)
assert body == "未解决线程 2 → 2，暂不 approve。", body

# More than five open threads: the list is capped, the count is not.
body = run_with_threads(
    9, 9,
    main.SettleOutcome(open=[
        {"path": f"f{i}.cs", "line": i, "reason": f"原因{i}", "body": ""} for i in range(9)
    ]),
)
assert body == "未解决线程 9 → 9，暂不 approve。", body
print("--- nine threads left: still one line")

body = run(-1, -1, main.SettleOutcome(unknown=True))
print("--- thread state unreadable")
print(body)
assert "读不到线程状态" in body, body

body = run_with_threads(2, 2, main.SettleOutcome(unknown=True))
assert "判定失败" in body, body
print("--- the decider failed")

# dry-run: says what it would do and touches nothing.
posted.clear()
settle_calls.clear()
ctx.config = types.SimpleNamespace(dry_run=True, language="cn")
main.unresolved_bot_thread_count = lambda gh, owner, repo, number: 5
main.settle_threads_and_approve = lambda *a, **k: settle_calls.append(k) or main.SettleOutcome()
main.handle_settle_command(ctx, command)
assert posted == [] and settle_calls == [], (posted, settle_calls)
print("dry-run: nothing posted, nothing settled, nothing approved")
print("OK")
