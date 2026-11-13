import io
import sys

PATH = r"E:\Gatongone\GitClone\ToolsWorkflow\review\main.py"

with io.open(PATH, encoding="utf-8") as fh:
    source = fh.read()


def replace(old, new, count=1):
    global source
    if source.count(old) != count:
        sys.exit(f"anchor found {source.count(old)} times: {old[:70]!r}")
    source = source.replace(old, new, count)


# 1. A review says what it is above the comments it carries.
replace(
    '''def buffer_inline_comments(''',
    '''def review_summary_body(language: str, count: int) -> str:
    """The line a review carries above its inline comments.

    A review has two kinds of text: its own body — the box at the top, where a
    person writes what they made of the change — and the body of each comment
    anchored to a line. Findings were filling the second and leaving the first
    empty, so the review arrived as a card with nothing to read on it.
    """
    chinese = "chinese" in resolve_language(language).lower()
    if chinese:
        return f"本审查发现 {count} 处问题，行内评论见下。"
    return (
        f"This review found {count} issue{'s' if count != 1 else ''}; "
        "they are inline below."
    )


def buffer_inline_comments(''',
)

# 2. An empty body is filled with it, so a review never arrives blank.
replace(
    '''    comments, ctx.buffered_comments = ctx.buffered_comments, []
    if not comments:
        return 0
    if not ctx.heads:
        log("Warning: no commit id available; skipping the comments.")
        return 0''',
    '''    comments, ctx.buffered_comments = ctx.buffered_comments, []
    if not comments:
        return 0
    if not ctx.heads:
        log("Warning: no commit id available; skipping the comments.")
        return 0
    if not body:
        body = review_summary_body(getattr(ctx.config, "language", ""), len(comments))''',
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(source)
print("patched")
