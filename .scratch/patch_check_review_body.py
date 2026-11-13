import io
import sys

PATH = r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_pending_review.py"

with io.open(PATH, encoding="utf-8") as fh:
    source = fh.read()

anchor = "print()\nif failures:"

addition = '''# 8. The review carries a line of its own above the comments. A review has two
#    kinds of text — its own body and each comment's body — and only the second was
#    filled, so the review arrived as a card with nothing to read on it.
gh = GitHub()
ctx = context(gh)
main._tool_post_inline_comment(comment("a finding"), ctx)
main.post_buffered_review(ctx)
body = gh.posted_reviews[0][0] if gh.posted_reviews else ""
if body and "1" in body:
    ok("the review says what it is above its comments")
else:
    bad(f"the review body is empty: {body!r}")

# 9. It is written in the language this repository asked for.
cn = main.review_summary_body("cn", 3)
en = main.review_summary_body("en", 1)
en_many = main.review_summary_body("en", 2)
if "3" in cn and "行内评论" in cn and "issue" in en and "issues" not in en and "issues" in en_many:
    ok("the summary follows the review language, and counts in English pluralise")
else:
    bad(f"cn={cn!r} en={en!r} en_many={en_many!r}")

# 10. A body the caller gives is what is sent; the summary only fills a blank.
gh = GitHub()
ctx = context(gh)
main._tool_post_inline_comment(comment("a finding"), ctx)
main.post_buffered_review(ctx, "已看过，见下。")
if gh.posted_reviews and gh.posted_reviews[0][0] == "已看过，见下。":
    ok("an explicit review body is kept")
else:
    bad(f"body={gh.posted_reviews[0][0] if gh.posted_reviews else None!r}")

'''

if source.count(anchor) != 1:
    sys.exit("anchor not found once")
source = source.replace(anchor, addition + anchor)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(source)
print("patched")
