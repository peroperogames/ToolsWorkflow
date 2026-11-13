"""Local check: a settle says everything in one message, and one notification.

Every thread it retired used to get its own reply, so a settle that closed five
threads arrived as five emails and a sixth saying what was left. The sentences fit
in the one message the settle posts — and the review pass that runs after a review
still replies in its threads, where there are few and the thread is the record.
"""

import json
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


def thread(tid, path, line, body="一个问题"):
    return {
        "id": tid,
        "path": path,
        "line": line,
        "isResolved": False,
        "comments": {
            "nodes": [
                {"author": {"login": "perotoolsbot[bot]"}, "body": body, "databaseId": 900 + line}
            ]
        },
    }


THREADS = [thread("PRRT_1", "Runtime/Foo.cs", 12), thread("PRRT_2", "Runtime/Bar.cs", 40)]


class GitHub:
    def __init__(self):
        self.replies = []
        self.resolved = []

    def list_review_threads(self, owner, repo, number):
        return [dict(t) for t in THREADS]

    def list_files(self, owner, repo, number):
        return [
            {"filename": "Runtime/Foo.cs", "patch": "@@ -1 +1 @@\n-a\n+b"},
            {"filename": "Runtime/Bar.cs", "patch": "@@ -1 +1 @@\n-c\n+d"},
        ]

    def get_file_content(self, owner, repo, path, ref=None):
        return "line one\nline two\n"

    def post_review_comment_reply(self, owner, repo, number, comment_id, body):
        self.replies.append(body)
        return {"id": 1}

    def resolve_review_thread(self, thread_id):
        self.resolved.append(thread_id)
        return True

    def thread_is_resolved(self, thread_id):
        return False


class AI:
    def __init__(self):
        self.answer = json.dumps(
            {
                "resolved": [
                    {"id": "PRRT_1", "reason": "检查已经移进 finally。"},
                    {"id": "PRRT_2", "reason": "作者说明不改，按作者决定关闭。"},
                ],
                "open": [],
            }
        )

    def chat(self, messages, **kwargs):
        return self.answer


PR = {"head": {"sha": "abc123"}}

# 1. The settle command path: no reply in any thread, both reasons in the outcome.
gh = GitHub()
outcome = main.decide_resolved_threads(
    AI(), gh, "o", "r", 3, PR, "perotoolsbot[bot]",
    diff_files=gh.list_files("o", "r", 3), language="cn", reply=False,
)
if not gh.replies and len(gh.resolved) == 2:
    ok("a settle resolves its threads and posts no reply in them")
else:
    bad(f"replies={gh.replies!r} resolved={gh.resolved!r}")

if [c["reason"] for c in outcome.closed] == [
    "✔️ 检查已经移进 finally。", "✔️ 作者说明不改，按作者决定关闭。",
]:
    ok("the sentence that closed each thread is kept in one list")
else:
    bad(f"closed={outcome.closed!r}")

body = main.settle_comment_body(6, 1, outcome)
if "已关闭 2 条：" in body and "`Runtime/Foo.cs:12` — ✔️ 检查已经移进 finally。" in body:
    ok("the settle message says what it closed, and why")
else:
    bad(body)

# 2. A message that closed nothing says nothing extra.
plain = main.SettleOutcome(resolved=0)
body = main.settle_comment_body(6, 1, plain)
if body == "未解决线程 6 → 1，暂不 approve。":
    ok("a settle that closed nothing says only the count")
else:
    bad(repr(body))

# 3. The review pass after a review still replies inside the threads it retires:
#    there the thread is the record, and there are only a few.
gh = GitHub()
outcome = main.decide_resolved_threads(
    AI(), gh, "o", "r", 3, PR, "perotoolsbot[bot]",
    diff_files=gh.list_files("o", "r", 3), language="cn", reply=True,
)
if len(gh.replies) == 2 and len(outcome.closed) == 2:
    ok("the retire pass after a review still explains itself in each thread")
else:
    bad(f"replies={gh.replies!r} closed={len(outcome.closed)}")

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("OK")
