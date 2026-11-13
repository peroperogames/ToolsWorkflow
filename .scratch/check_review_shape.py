"""Local check: one review carries everything the run found.

Three shapes are pinned here.

- A review has a body of its own — the box at the top — and it is filled with text
  the run already has (the build and test result), never with a sentence invented
  to fill it. When there is nothing to say, it stays empty.
- The static analysis's findings ride in that same review instead of arriving
  first as comments of their own, and are posted if the review step never carried
  them, so nothing is lost.
- `settle` says its result as a review body, not as an issue comment.
"""

import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main
import stage_state

failures = []


def ok(msg):
    print("ok   " + msg)


def bad(msg):
    print("FAIL " + msg)
    failures.append(msg)


FILES = [
    {
        "filename": "Core/Thing.cs",
        "status": "modified",
        "additions": 1,
        "deletions": 0,
        "patch": "@@ -10,1 +10,2 @@\n public void Existing() { }\n+public void Added() { }",
    }
]
PR = {"head": {"sha": "abc123"}}
QUOTE = "public void Added() { }"


class GitHub:
    def __init__(self):
        self.posted_reviews = []
        self.direct = []
        self.comments = []

    def post_review(self, owner, repo, number, body, event="COMMENT", comments=None):
        comments = list(comments or [])
        self.posted_reviews.append((body, event, comments))
        return {
            "id": 1,
            "state": "COMMENTED",
            "comments": [{"id": 100 + i} for i in range(len(comments))],
        }

    def post_review_comment(self, owner, repo, number, commit_id, comment):
        self.direct.append(comment)
        return {"id": 900 + len(self.direct)}

    def list_review_comments(self, owner, repo, number):
        return []

    def post_comment(self, owner, repo, number, body):
        self.comments.append(body)
        return {"id": 5}


def context(gh):
    return main.ToolContext(
        gh=gh, owner="o", repo="r", number=1, pr=PR, files=FILES,
        config=types.SimpleNamespace(dry_run=False, language="cn"), heads="abc123",
    )


def finding(body="a finding"):
    return {"path": "Core/Thing.cs", "quote": QUOTE, "body": body}


# 1. Nothing to say: the review body stays empty. No sentence is invented for it.
gh = GitHub()
ctx = context(gh)
main._tool_post_inline_comment(finding(), ctx)
main.post_buffered_review(ctx)
if gh.posted_reviews and gh.posted_reviews[0][0] == "":
    ok("a review with nothing to say carries no invented body")
else:
    bad(f"body={gh.posted_reviews[0][0]!r}")

# 2. The build/test result is what the body carries when the run has one.
gh = GitHub()
ctx = context(gh)
main._tool_post_inline_comment(finding(), ctx)
status = "## 构建与测试状态\n\n✅ Unity: 编译通过，单元测试通过。"
main.post_buffered_review(ctx, status)
if gh.posted_reviews and gh.posted_reviews[0][0] == status:
    ok("the build and test result is the review's body")
else:
    bad(f"body={gh.posted_reviews[0][0] if gh.posted_reviews else None!r}")

# 3. The static analysis's findings are carried into one review, and cleared.
tmp = Path(tempfile.mkdtemp()) / "state.json"
main._state_path = lambda owner, repo, number: tmp
held = [finding("ReSharper: first"), finding("ReSharper: second")]
stage_state.save(
    stage_state.CheckState(
        head_sha="abc123",
        run_key=stage_state.current_run(),
        static_posted=len(held),
        static_comments=held,
    ),
    tmp,
)
gh = GitHub()
main._post_unclaimed_static_comments(gh, "o", "r", 1, PR)
left = stage_state.load(tmp, "abc123")
if (
    len(gh.posted_reviews) == 1
    and len(gh.posted_reviews[0][2]) == 2
    and gh.posted_reviews[0][1] == "COMMENT"
    and gh.direct == []
    and left is not None
    and left.static_comments == []
):
    ok("findings no review carried are posted as one review, then forgotten")
else:
    bad(f"reviews={gh.posted_reviews!r} direct={len(gh.direct)} left={left and left.static_comments}")

# 4. Nothing held: nothing is posted.
gh = GitHub()
main._post_unclaimed_static_comments(gh, "o", "r", 1, PR)
if not gh.posted_reviews and not gh.comments:
    ok("a run with no held findings posts nothing extra")
else:
    bad(f"reviews={len(gh.posted_reviews)} comments={len(gh.comments)}")

# 5. The findings survive a review that never ran, and are not posted twice.
stage_state.save(
    stage_state.CheckState(
        head_sha="abc123", run_key=stage_state.current_run(), static_comments=held
    ),
    tmp,
)
if main._read_static_comments("o", "r", 1, PR) and main._read_static_comments("o", "r", 1, PR):
    ok("reading the held findings does not consume them")
else:
    bad("the findings were consumed before a review carried them")

source = (
    Path(__file__).resolve().parent.parent / "review" / "main.py"
).read_text(encoding="utf-8")

# 6. `settle` says its result as a review body.
if 'post_review(\n            ctx.owner, ctx.repo, ctx.number, result, event="COMMENT"\n        )' in source:
    ok("the settle result is posted as a review body")
else:
    bad("settle still posts its result as a plain comment")

# 7. The static stage holds its findings only when a review will carry them.
if (
    'carried = "review" in _wanted_stages(event_name, payload)' in source
    and "collector=held," in source
    and "if held and not carried:" in source
    and "_post_unclaimed_static_comments(gh, owner, repo, number, pr, held)" in source
):
    ok("the analysis is held for the review, or posted as one review when there is none")
else:
    bad("the analysis still arrives as one comment per finding")

# 8. The review stage asks the state for the result and the held findings.
if (
    'review_body=checks_state.extra_context if checks_state else ""' in source
    and "carried_comments=carried," in source
):
    ok("the review step is handed both the result and the held findings")
else:
    bad("the review step does not receive the result or the held findings")

# 9. The command path builds the same review as a push does. It was the one path
#    left out: `@perotoolsbot review` posted an empty body and lost the analysis's
#    findings, because only the push path handed them over.
command_call = source[
    source.index("def handle_review_request("):
    source.index("def settle_after_review(")
]
if (
    "review_body=review_body," in command_call
    and "carried_comments=_read_static_comments(owner, repo, number, pr)" in command_call
    and "review_body = gates.extra_context" in command_call
):
    ok("a review asked for by command carries the result and the held findings")
else:
    bad("the command path still posts an empty review body")

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("OK")
