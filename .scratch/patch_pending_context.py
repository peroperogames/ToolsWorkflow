"""One-off: make the pending-review helpers work without a ToolContext.

The ReSharper batch posts 10-20 comments from its own process, so it needs the same
one-review submit; a helper that only takes a `ToolContext` cannot serve it.
"""

from pathlib import Path

main_py = Path(__file__).resolve().parent.parent / "review" / "main.py"
text = main_py.read_text(encoding="utf-8")

start = text.index('def _existing_pending_review(ctx: "ToolContext") -> Any:')
end = text.index("def index_diff_lines(patch: str)")

new_block = '''def _existing_pending_review(
    gh: GitHubClient, owner: str, repo: str, number: int
) -> Any:
    """The pending review an earlier run of this bot left behind, if any.

    A run that dies between its first comment and its submit leaves one, and GitHub
    allows only one pending review per user per pull request: without finding it,
    every later run would fail to start a review of its own. Reusing it also
    delivers what that run found.
    """
    try:
        for review in gh.list_reviews(owner, repo, number):
            if (review.get("state") or "").upper() != "PENDING":
                continue
            if is_bot_author(review.get("user")):
                return review.get("id")
    except Exception as exc:  # noqa: BLE001 - best effort
        log(f"Could not look for an earlier pending review: {exc}")
    return None


def _pending_review(
    gh: GitHubClient, owner: str, repo: str, number: int, commit_id: str
) -> Any:
    """The pull request's pending review, started on its first comment."""
    existing = _existing_pending_review(gh, owner, repo, number)
    if existing is not None:
        log("Reusing the pending review an earlier run left on this pull request.")
        return existing
    try:
        review = gh.create_pending_review(owner, repo, number, commit_id)
    except Exception as exc:  # noqa: BLE001 - post them the old way instead
        log(f"Warning: could not start a pending review ({exc}).")
        return None
    return (review or {}).get("id") if isinstance(review, dict) else None


def add_comments_to_pending_review(
    gh: GitHubClient,
    owner: str,
    repo: str,
    number: int,
    commit_id: str,
    comments: List[Dict[str, Any]],
) -> "Tuple[Any, List[Dict[str, Any]]]":
    """Write comments into one pending review, invisible until it is submitted.

    Nothing appears on the pull request before that, which is the whole point: a
    review that says six things is one review, not six — one notification, one
    timeline entry, and nothing half-posted if the run dies.

    Returns the review's id and the comments actually added. The id is None when
    there is no review to add to (it could not be started, or there is no commit to
    anchor to), and the caller posts them the old way instead.
    """
    added: List[Dict[str, Any]] = []
    if not comments:
        return None, added
    if not commit_id:
        log("Warning: no commit id available; skipping inline comments.")
        return None, added
    review_id = _pending_review(gh, owner, repo, number, commit_id)
    if review_id is None:
        return None, added
    for comment in comments:
        try:
            gh.add_review_comment(owner, repo, number, review_id, comment)
            added.append(comment)
        except Exception as exc:  # noqa: BLE001 - one bad comment, not the review
            log(
                "Warning: could not add the comment "
                f"({comment.get('path')}:{comment.get('line')}): {exc}"
            )
    log(f"Added {len(added)}/{len(comments)} comment(s) to the pending review.")
    return review_id, added


def submit_pending_review(
    gh: GitHubClient,
    owner: str,
    repo: str,
    number: int,
    commit_id: str,
    review_id: Any,
    comments: List[Dict[str, Any]],
    posted_ids: Optional[List[int]] = None,
) -> int:
    """Submit the review, and remember which comments it posted.

    The ids matter twice over: they are what the log reports, and the retirement
    pass that runs next must not resolve a thread from this run's own findings.
    GitHub answers with them; when it does not, they are read back from the pull
    request.

    A refused submit falls back to posting the comments one by one. Six comments as
    six reviews is the shape this avoids — but a lost review is worse than a noisy
    one.
    """
    if review_id is None:
        return 0
    try:
        submitted = gh.submit_review(owner, repo, number, review_id, "COMMENT")
    except Exception as exc:  # noqa: BLE001 - never lose the findings
        log(
            f"Warning: could not submit the review ({exc}); posting its comments "
            "one by one instead."
        )
        return post_inline_comments(
            gh, owner, repo, number, commit_id, comments, posted_ids=posted_ids
        )
    found = (submitted or {}).get("comments") or []
    if not found:
        try:
            found = [
                comment
                for comment in gh.list_review_comments(owner, repo, number)
                if comment.get("pull_request_review_id") == review_id
            ]
        except Exception as exc:  # noqa: BLE001 - best effort
            log(f"Warning: could not read the submitted review's comments: {exc}")
    for comment in found:
        comment_id = (comment or {}).get("id")
        if posted_ids is not None and isinstance(comment_id, int):
            posted_ids.append(comment_id)
    log(f"Submitted one review carrying {len(comments)} inline comment(s).")
    return len(comments)


def submit_this_run_review(ctx: "ToolContext") -> int:
    """Submit the review a run was writing into, and forget it."""
    review_id, comments = ctx.pending_review_id, ctx.pending_comments
    ctx.pending_review_id, ctx.pending_comments = None, []
    if review_id is None:
        return 0
    return submit_pending_review(
        ctx.gh, ctx.owner, ctx.repo, ctx.number, ctx.heads, review_id, comments,
        ctx.posted_ids,
    )


'''

text = text[:start] + new_block + text[end:]


def replace(old: str, new: str) -> None:
    global text
    assert text.count(old) == 1, (text.count(old), old[:70])
    text = text.replace(old, new)


# The tool: into the pending review, or the old way when there is no review to add to.
replace(
    """    posted = post_inline_comments_pending(ctx, normalized)""",
    """    review_id, added = add_comments_to_pending_review(
        ctx.gh, ctx.owner, ctx.repo, ctx.number, ctx.heads, normalized
    )
    if review_id is None:
        posted = post_inline_comments(
            ctx.gh, ctx.owner, ctx.repo, ctx.number, ctx.heads, normalized,
            posted_ids=ctx.posted_ids,
        )
    else:
        ctx.pending_review_id = review_id
        ctx.pending_comments.extend(added)
        posted = len(added)""",
)

# The three agent exits submit through the context.
text = text.replace("    submit_pending_review(ctx)\n", "    submit_this_run_review(ctx)\n")
text = text.replace(
    "                submit_pending_review(ctx)\n", "                submit_this_run_review(ctx)\n"
)

# The ReSharper batch gets one review too.
replace(
    """    return post_inline_comments(
        gh, owner, repo, number, pr.get("head", {}).get("sha", ""), normalized
    )""",
    """    # One review, not one per finding: the batch is written into a pending review
    # and submitted once, so a pull request with fifteen inspection findings still
    # gets one review from the run.
    heads = pr.get("head", {}).get("sha", "")
    review_id, added = add_comments_to_pending_review(
        gh, owner, repo, number, heads, normalized
    )
    if review_id is None:
        return post_inline_comments(gh, owner, repo, number, heads, normalized)
    return submit_pending_review(
        gh, owner, repo, number, heads, review_id, added
    )""",
)

main_py.write_text(text, encoding="utf-8", newline="\n")
print("patched")
