"""Local check: a reply that closed the threads still settles and approves.

From AccessKing PR #3: the model resolved ten threads, finished with no reply text,
and the run ended — no approval, ten closed threads. The empty-reply branch
returned before the settle/approve step ever ran.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main

calls = []


def fake_settle(ai, gh, owner, repo, number, pr, **kwargs):
    calls.append(kwargs)


main.settle_threads_and_approve = fake_settle

config = types.SimpleNamespace(dry_run=False, language="cn")
pr = {"head": {"sha": "abc123"}}


def ctx(resolved=0, posted=0, posted_ids=()):
    value = main.ToolContext(
        gh=None, owner="o", repo="r", number=3, pr=pr, files=[],
        config=config, heads="abc123",
    )
    value.resolved_threads = resolved
    value.inline_posted = posted
    value.posted_ids = list(posted_ids)
    return value


# The case from the log: ten threads closed, nothing to say.
main.settle_after_reply_actions(None, None, "o", "r", 3, pr, config, ctx(resolved=10))
assert len(calls) == 1, calls
print("resolved threads, empty reply -> settle and approve is called")

# New inline findings and no reply: still settles (approval then declines on the
# open thread, which is approve_if_clean's job, not this one's).
calls.clear()
main.settle_after_reply_actions(
    None, None, "o", "r", 3, pr, config, ctx(posted=1, posted_ids=[77])
)
assert len(calls) == 1 and calls[0]["skip_ids"] == [77], calls
print("posted inline comment, empty reply -> settle, and this run's own ids are skipped")

# Nothing done at all: nothing to decide from it, so nothing is called — an
# unrelated comment must not approve an unreviewed pull request.
calls.clear()
main.settle_after_reply_actions(None, None, "o", "r", 3, pr, config, ctx())
assert calls == [], calls
print("no action at all -> no settle, no approval")

# dry-run says what it would do and does nothing; no reply context at all is the
# same no-op.
calls.clear()
dry = types.SimpleNamespace(dry_run=True, language="cn")
main.settle_after_reply_actions(None, None, "o", "r", 3, pr, dry, ctx(resolved=3))
main.settle_after_reply_actions(None, None, "o", "r", 3, pr, config, None)
assert calls == [], calls
print("dry-run and no reply context -> nothing happens")

# --- the `approve` tool: it approves, or names what blocks it, and never claims a
# permission it cannot see. RhythmAce-Neo #108 answered "我没有提交 approve 的权限"
# one minute before the bot approved that same pull request.
main.update_standing_comment = lambda *a, **k: False
main.clean_verdict_body = lambda *a, **k: "body"
main.CLEAN_VERDICT_MARKER = "<!-- marker -->"


def approve_ctx():
    value = main.ToolContext(
        gh=types.SimpleNamespace(), owner="o", repo="r", number=3, pr=pr, files=[],
        config=config, heads="abc123",
    )
    return value


main.already_approved = lambda *a, **k: False
main.unresolved_bot_thread_count = lambda *a, **k: 0
main.approve_if_clean = lambda *a, **k: True
value = approve_ctx()
answer = main._tool_approve({}, value)
assert value.approved and answer.startswith("approved"), (answer, value.approved)
print("asked to approve with nothing open -> it approves")

main.approve_if_clean = lambda *a, **k: False
main.unresolved_bot_thread_count = lambda *a, **k: 3
answer = main._tool_approve({}, approve_ctx())
assert "3 review thread(s)" in answer, answer
assert "权限" not in answer and "permission" not in answer.lower(), answer
print("three threads open -> it names them, and does not invent a permission")

main.already_approved = lambda *a, **k: True
main.unresolved_bot_thread_count = lambda *a, **k: 0
answer = main._tool_approve({}, approve_ctx())
assert "already" in answer, answer
print("a commit that is already approved is not approved again")

dry_value = main.ToolContext(
    gh=types.SimpleNamespace(), owner="o", repo="r", number=3, pr=pr, files=[],
    config=types.SimpleNamespace(dry_run=True, language="cn"), heads="abc123",
)
assert main._tool_approve({}, dry_value).startswith("dry-run"), "dry run must not approve"
print("a dry run says what it would do and approves nothing")
print("OK")
