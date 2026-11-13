"""One-off: document one-review-per-run, and check the batch path that uses it."""

from pathlib import Path

root = Path(__file__).resolve().parent.parent
readme = root / "review" / "README.md"
check = root / ".scratch" / "check_pending_review.py"

text = readme.read_text(encoding="utf-8")
anchor = "### A big diff is reviewed in slices, not carried through every step"
assert text.count(anchor) == 1
section = """### One review, not one per comment

Every finding used to be a `post_inline_comment` call, and every call created its own review: RhythmAce-Neo #65 finished with fifteen COMMENTED reviews for fifteen comments, each with its own notification and timeline entry, and a run that died halfway left half of them posted — which reads as a review that changed its mind.

A run now writes into **one pending review** and submits it at the end. `post_inline_comment` adds to the pending review, so nothing is visible on the pull request while the model is still deciding what to say; the review is submitted once, when the run finishes. The ReSharper batch goes through the same code, so its fifteen findings are one review too.

GitHub allows **one pending review per user per pull request** — a second create is refused with `User can only have one pending review per pull request` — so a pending review left behind by a run that died is reused by the next run rather than fought with, and what that run found is delivered with it. When the review cannot be started, or GitHub refuses the submit, the comments are posted one by one as before: six reviews is worse than one, and a lost review is worse than six.

"""
readme.write_text(
    text.replace(anchor, section + anchor), encoding="utf-8", newline="\n"
)

t = check.read_text(encoding="utf-8")
old = '''print()
if failures:'''
new = '''# 7. The ReSharper batch is one review too: the same helpers, no agent involved.
gh = GitHub()
review_id, added = main.add_comments_to_pending_review(
    gh, "o", "r", 9, "abc123",
    [comment("inspection one"), comment("inspection two")],
)
main.submit_pending_review(gh, "o", "r", 9, "abc123", review_id, added)
if gh.created == 1 and gh.submitted == 1 and len(gh.added) == 2 and gh.posted == []:
    ok("a batch of findings is one review, not one per finding")
else:
    bad(f"created={gh.created}, submitted={gh.submitted}, added={len(gh.added)}")

print()
if failures:'''
assert t.count(old) == 1
check.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
