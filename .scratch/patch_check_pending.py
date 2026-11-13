import io

PATH = r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_pending_review.py"
source = io.open(PATH, encoding="utf-8").read()

start = source.index("# 8. The review carries a line of its own above the comments.")
block_end = source.index(
    "# 10. A body the caller gives is what is sent; the summary only fills a blank."
)
kept = source[block_end:]

replacement = '''# 8. Nothing is invented for the review body: a buffered review with nothing to say
#    carries an empty one. (Which real text fills it is pinned in check_review_shape.py.)
gh = GitHub()
ctx = context(gh)
main._tool_post_inline_comment(comment("a finding"), ctx)
main.post_buffered_review(ctx)
if gh.posted_reviews and gh.posted_reviews[0][0] == "":
    ok("a buffered review without a body says nothing above its comments")
else:
    bad(f"body={gh.posted_reviews[0][0] if gh.posted_reviews else None!r}")

'''

source = source[:start] + replacement + kept
source = source.replace(
    "# 10. A body the caller gives is what is sent; the summary only fills a blank.",
    "# 9. A body the caller gives is what is sent.",
)
io.open(PATH, "w", encoding="utf-8", newline="\n").write(source)
print("patched")
