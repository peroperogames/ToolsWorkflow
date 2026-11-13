"""Local check: a clean review that cannot approve still says it ran."""

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


class FakeGitHub:
    def __init__(self):
        self.comments = []
        self.posted = 0
        self.edits = 0
        self.reviews = []

    def list_comments(self, owner, repo, number):
        return [{"id": index + 1, "body": body, "user": {"login": "bot"}}
                for index, body in enumerate(self.comments)]

    def post_comment(self, owner, repo, number, body):
        self.posted += 1
        self.comments.append(body)
        return {"id": len(self.comments)}

    def update_comment(self, owner, repo, comment_id, body):
        self.edits += 1
        self.comments[comment_id - 1] = body
        return {"id": comment_id}

    def post_review(self, owner, repo, number, body, event=None):
        self.reviews.append(event)
        return {}


def context(language="zh", inline_posted=False, dry_run=False):
    return types.SimpleNamespace(
        config=types.SimpleNamespace(dry_run=dry_run, language=language),
        pr={"head": {"sha": "abc123"}},
        approved=False,
        inline_posted=inline_posted,
    )


# A fake bot user: `is_bot_author` decides whether a comment is ours.
main.is_bot_author = lambda user: (user or {}).get("login") == "bot"

# 1. Clean verdict, three threads open, nothing posted: the pull request is told.
gh = FakeGitHub()
main.approve_if_clean = lambda *args, **kwargs: False
main.already_approved = lambda *args, **kwargs: False
main.unresolved_bot_thread_count = lambda *args, **kwargs: 3
ctx = context()
main.act_on_clean_verdict(gh, "o", "r", 80, ctx)
body = gh.comments[0] if gh.comments else ""
print("--- body:", " ".join(body.split())[:80])
if "没有发现新问题" in body and "3 个审查线程" in body and not ctx.approved:
    ok("a clean verdict that cannot approve posts one comment naming the open count")
else:
    bad(f"a clean verdict posted {gh.comments!r}")

# 2. The next run edits that comment instead of stacking another.
main.act_on_clean_verdict(gh, "o", "r", 80, context())
if gh.posted == 1 and gh.edits == 1:
    ok("a second run edits the same comment")
else:
    bad(f"posted={gh.posted}, edits={gh.edits}")

# 3. Once it can approve, the sentence "not approved" must stop being true.
main.approve_if_clean = lambda *args, **kwargs: True
ctx = context()
main.act_on_clean_verdict(gh, "o", "r", 80, ctx)
if ctx.approved and gh.posted == 1 and "已批准" in gh.comments[0]:
    ok("an approval corrects the earlier comment instead of leaving it wrong")
else:
    bad(f"approved={ctx.approved}, comments={gh.comments!r}")

# 4. A first approval has nothing to correct: no comment at all.
gh = FakeGitHub()
main.act_on_clean_verdict(gh, "o", "r", 80, context())
if gh.posted == 0 and gh.reviews == []:
    ok("an approval on a clean pull request posts nothing")
else:
    bad(f"posted={gh.posted}, reviews={gh.reviews}")

# 5. Findings are on the pull request already: no status comment on top of them.
gh = FakeGitHub()
main.approve_if_clean = lambda *args, **kwargs: False
main.act_on_clean_verdict(gh, "o", "r", 80, context(inline_posted=True))
if gh.posted == 0:
    ok("a clean verdict with inline comments posts no extra comment")
else:
    bad(f"posted={gh.posted}")

# 6. English, when that is the review language.
gh = FakeGitHub()
main.act_on_clean_verdict(gh, "o", "r", 80, context(language="en"))
if gh.comments and "3 review thread(s)" in gh.comments[0] and "not approved" in gh.comments[0]:
    ok("the comment follows the review language")
else:
    bad(f"english body: {gh.comments!r}")

# 7. A dry run decides nothing and posts nothing.
gh = FakeGitHub()
main.act_on_clean_verdict(gh, "o", "r", 80, context(dry_run=True))
if gh.posted == 0:
    ok("a dry run posts nothing")
else:
    bad(f"dry run posted {gh.posted}")

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("OK")
