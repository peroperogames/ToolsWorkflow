"""Local check: a run buffers its findings and posts them as one review.

The pending-review attempt was wrong twice over. `POST /reviews/{id}/comments` does not
exist — GitHub answers 404, whatever the review — and a pending review that already
exists blocks a new review and an approval (422). RhythmAce-Neo #108 lost two runs to it.

What the API does support is one review carrying many comments, which is both simpler
and exactly the behaviour asked for: nothing visible until the run is finished.
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


FILES = [
    {
        "filename": "Core/Thing.cs",
        "status": "modified",
        "additions": 2,
        "deletions": 1,
        "patch": "@@ -10,2 +10,3 @@\n- old line\n+public void Register(IHandler handler) { }\n+public void Unregister() { }",
    }
]
QUOTE = "public void Register(IHandler handler) { }"
PR = {"head": {"sha": "abc123"}}
BOT = {"login": "perotoolsbot[bot]"}

main.is_bot_author = lambda user: (user or {}).get("login") == "perotoolsbot[bot]"


class GitHub:
    def __init__(self, reviews=(), post_error=None, returns_comments=True):
        self.reviews = [dict(r) for r in reviews]
        self.post_error = post_error
        self.returns_comments = returns_comments
        self.posted_reviews = []      # (body, event, comments)
        self.direct = []              # comments posted one by one
        self.deleted = []
        self.listed_comments = 0

    def list_reviews(self, owner, repo, number):
        return [dict(r) for r in self.reviews]

    def delete_review(self, owner, repo, number, review_id):
        self.deleted.append(review_id)
        self.reviews = [r for r in self.reviews if r.get("id") != review_id]
        return {"id": review_id}

    def post_review(self, owner, repo, number, body, event="COMMENT", comments=None):
        comments = list(comments or [])
        self.posted_reviews.append((body, event, comments))
        if self.post_error:
            raise RuntimeError(self.post_error)
        if not self.returns_comments:
            return {"id": 4242, "state": "COMMENTED"}
        return {
            "id": 4242,
            "state": "COMMENTED",
            "comments": [{"id": 900 + index} for index in range(1, len(comments) + 1)],
        }

    def list_review_comments(self, owner, repo, number):
        self.listed_comments += 1
        count = len(self.posted_reviews[-1][2]) if self.posted_reviews else 0
        return [{"id": 901 + index, "pull_request_review_id": 4242} for index in range(count)]

    def post_review_comment(self, owner, repo, number, commit_id, comment):
        self.direct.append(comment)
        return {"id": 1000 + len(self.direct)}


def context(gh, dry_run=False):
    return main.ToolContext(
        gh=gh, owner="o", repo="r", number=12, pr=PR, files=FILES,
        config=types.SimpleNamespace(dry_run=dry_run), heads="abc123",
    )


def comment(body):
    return {"path": "Core/Thing.cs", "quote": QUOTE, "body": body}


# 1. Posting buffers: nothing goes to GitHub.
gh = GitHub()
ctx = context(gh)
main._tool_post_inline_comment(comment("first finding"), ctx)
main._tool_post_inline_comment(comment("second finding"), ctx)
if len(ctx.buffered_comments) == 2 and not gh.posted_reviews and not gh.direct:
    ok("findings are buffered; the pull request sees nothing yet")
else:
    bad(
        f"buffered={len(ctx.buffered_comments)}, reviews={len(gh.posted_reviews)}, "
        f"direct={len(gh.direct)}"
    )

# 2. The end of the run posts them as ONE review.
main.post_buffered_review(ctx)
if len(gh.posted_reviews) == 1 and len(gh.posted_reviews[0][2]) == 2 and gh.direct == []:
    ok("the buffered findings go out as one review, in one call")
else:
    bad(f"reviews={len(gh.posted_reviews)}, direct={len(gh.direct)}")

if ctx.posted_ids == [901, 902] and ctx.buffered_comments == []:
    ok("the posted comments' ids are known and the buffer is empty")
else:
    bad(f"posted_ids={ctx.posted_ids}, buffered={len(ctx.buffered_comments)}")

# 3. GitHub answers without the comment list: they are read back.
gh = GitHub(returns_comments=False)
ctx = context(gh)
main._tool_post_inline_comment(comment("a finding"), ctx)
main.post_buffered_review(ctx)
if gh.listed_comments == 1 and ctx.posted_ids == [901]:
    ok("a response without comments still tells the run what it posted")
else:
    bad(f"listed={gh.listed_comments}, posted_ids={ctx.posted_ids}")

# 4. A review GitHub refuses: the comments are posted one by one, not lost.
gh = GitHub(post_error="GitHub API error (422) POST .../reviews: Validation Failed")
ctx = context(gh)
main._tool_post_inline_comment(comment("a finding"), ctx)
main.post_buffered_review(ctx)
if len(gh.direct) == 1 and ctx.posted_ids == [1001]:
    ok("a refused review falls back to posting its comments, and records them")
else:
    bad(f"direct={len(gh.direct)}, posted_ids={ctx.posted_ids}")

# 5. Nothing buffered: no review is posted.
gh = GitHub()
ctx = context(gh)
main.post_buffered_review(ctx)
if not gh.posted_reviews:
    ok("a review with no findings posts nothing")
else:
    bad(f"posted {len(gh.posted_reviews)} review(s) with nothing in them")

# 6. The same finding twice is still refused, and a dry run posts nothing.
gh = GitHub()
ctx = context(gh)
main._tool_post_inline_comment(comment("the same finding"), ctx)
second = main._tool_post_inline_comment(comment("the same finding"), ctx)
if second.startswith("skipped") and len(ctx.buffered_comments) == 1:
    ok("a repeated finding is still refused before it reaches the buffer")
else:
    bad(f"second={second!r}, buffered={len(ctx.buffered_comments)}")

gh = GitHub()
ctx = context(gh, dry_run=True)
main._tool_post_inline_comment(comment("a finding"), ctx)
main.post_buffered_review(ctx)
if ctx.buffered_comments == [] and not gh.posted_reviews:
    ok("a dry run buffers and posts nothing")
else:
    bad(f"buffered={len(ctx.buffered_comments)}, reviews={len(gh.posted_reviews)}")

# 7. A leftover pending review is deleted before anything is posted: it blocks a new
#    review and an approval while it exists.
gh = GitHub(reviews=[
    {"id": 1, "state": "PENDING", "user": BOT},
    {"id": 2, "state": "COMMENTED", "user": BOT},
    {"id": 3, "state": "PENDING", "user": {"login": "tanyyt"}},
])
removed = main.clear_leftover_pending_reviews(gh, "o", "r", 12)
if removed == 1 and gh.deleted == [1]:
    ok("leftover pending reviews of this bot are deleted, and nobody else's are touched")
else:
    bad(f"removed={removed}, deleted={gh.deleted}")

# 8. Nothing is invented for the review body: a buffered review with nothing to say
#    carries an empty one. (Which real text fills it is pinned in check_review_shape.py.)
gh = GitHub()
ctx = context(gh)
main._tool_post_inline_comment(comment("a finding"), ctx)
main.post_buffered_review(ctx)
if gh.posted_reviews and gh.posted_reviews[0][0] == "":
    ok("a buffered review without a body says nothing above its comments")
else:
    bad(f"body={gh.posted_reviews[0][0] if gh.posted_reviews else None!r}")

# 9. A body the caller gives is what is sent.
gh = GitHub()
ctx = context(gh)
main._tool_post_inline_comment(comment("a finding"), ctx)
main.post_buffered_review(ctx, "已看过，见下。")
if gh.posted_reviews and gh.posted_reviews[0][0] == "已看过，见下。":
    ok("an explicit review body is kept")
else:
    bad(f"body={gh.posted_reviews[0][0] if gh.posted_reviews else None!r}")

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("OK")
