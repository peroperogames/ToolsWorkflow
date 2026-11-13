"""Local check: a thread that stays open gets no comment; a resolved one still does.

The settle run used to post the decider's "what is still missing" sentence into the
thread with `⏳ 仍未关闭：…`. It no longer posts anything there — an open thread is
already visible as an open thread, and the reason is only in the run log — while a
resolution still explains itself inside the thread it closes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main


class FakeAI:
    def __init__(self, payload):
        self.payload = payload
        self.messages = []

    def chat(self, messages, temperature=0.0):
        self.messages = messages
        return self.payload


class FakeGitHub:
    def __init__(self, threads):
        self.replies = []
        self.resolved = []
        self._threads = threads

    def list_review_threads(self, owner, repo, number):
        return self._threads

    def path_exists(self, owner, repo, path, ref=None):
        return True

    def post_review_comment_reply(self, owner, repo, number, comment_id, body):
        self.replies.append((comment_id, body))
        return {"id": 11}

    def resolve_review_thread(self, thread_id):
        self.resolved.append(thread_id)
        return {}


def thread(tid, comment_id, body="这个文件不该提交"):
    return {
        "id": tid,
        "path": "AndroidProject~/.project",
        "line": 12,
        "isResolved": False,
        "comments": {"nodes": [
            {"author": {"login": "perotoolsbot[bot]"}, "body": body, "databaseId": comment_id},
        ]},
    }


def run(payload, threads=None):
    gh = FakeGitHub(threads or [thread("T1", 9)])
    outcome = main.decide_resolved_threads(
        FakeAI(payload), gh, "o", "r", 3, {"head": {"sha": "abc123"}},
        "perotoolsbot[bot]", language="zh",
    )
    return outcome, gh


# The whole point: the decider says "still open, here is why" and nothing is posted.
outcome, gh = run('{"resolved": [], "open": [{"id": "T1", "reason": "新提交没有改动这个文件。"}]}')
print("--- replies for a thread left open:", gh.replies)
assert gh.replies == [], gh.replies
assert gh.resolved == [], gh.resolved
assert outcome.resolved == 0
# The reason is not thrown away: it is what the run log reports.
assert outcome.open and outcome.open[0]["reason"] == "新提交没有改动这个文件。", outcome.open

# No reason from the decider, and the thread simply left out of the answer: also silent.
outcome, gh = run('{"resolved": [], "open": [{"id": "T1", "reason": ""}]}')
assert gh.replies == [], gh.replies
outcome, gh = run('{"resolved": []}')
assert gh.replies == [], gh.replies
print("--- no reason, and a thread left out of the answer: still nothing posted")

# A resolution is unchanged: the note inside the thread, then the resolve.
outcome, gh = run('{"resolved": [{"id": "T1", "reason": "三个文件已从 PR 移除。"}], "open": []}')
print("--- replies for a resolved thread:", gh.replies)
assert gh.replies == [(9, "✔️ 三个文件已从 PR 移除。")], gh.replies
assert gh.resolved == ["T1"], gh.resolved
assert outcome.resolved == 1 and outcome.open == []

# Two threads, one each way: only the resolved one is touched.
outcome, gh = run(
    '{"resolved": [{"id": "T2", "reason": "已修。"}], "open": [{"id": "T1", "reason": "还差错误处理。"}]}',
    threads=[thread("T1", 9), thread("T2", 10)],
)
assert gh.replies == [(10, "✔️ 已修。")], gh.replies
assert gh.resolved == ["T2"], gh.resolved
assert [item["reason"] for item in outcome.open] == ["还差错误处理。"], outcome.open
print("--- one resolved, one open: only the resolved thread is written to")

# The note builder for open threads is gone, not merely unused.
assert not hasattr(main, "_open_note"), "the open note still exists"
print("--- _open_note is gone")
print("OK")
