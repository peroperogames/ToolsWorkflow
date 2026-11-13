"""One-off: a review run writes into one pending review and submits it at the end."""

from pathlib import Path

root = Path(__file__).resolve().parent.parent
main_py = root / "review" / "main.py"
client_py = root / "review" / "github_client.py"

client = client_py.read_text(encoding="utf-8")
main = main_py.read_text(encoding="utf-8")


def replace(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, (text.count(old), old[:70])
    return text.replace(old, new)


# --------------------------------------------------------------------------- #
# github_client: the three calls a pending review needs, and the list of them.
# --------------------------------------------------------------------------- #
client = replace(
    client,
    """    def compare(
        self, owner: str, repo: str, base: str, head: str
    ) -> List[Dict[str, Any]]:""",
    '''    def create_pending_review(
        self, owner: str, repo: str, number: int, commit_id: str
    ) -> Dict[str, Any]:
        """Start a review that stays pending until it is submitted.

        A review created without an `event` is a draft: comments added to it are
        invisible on the pull request until it is submitted, which is what lets a
        run that posts findings one model step at a time reach the author as one
        review. GitHub allows **one** pending review per user per pull request, so
        a create can fail with "User can only have one pending review per pull
        request" — see `pending_review_id`, which reuses the leftover instead.
        """
        payload: Dict[str, Any] = {"commit_id": commit_id} if commit_id else {}
        return self._request(
            "POST", f"/repos/{owner}/{repo}/pulls/{number}/reviews", json=payload
        )

    def add_review_comment(
        self,
        owner: str,
        repo: str,
        number: int,
        review_id: Any,
        comment: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Add one inline comment to a review that is still pending."""
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{number}/reviews/{review_id}/comments",
            json=dict(comment),
        )

    def submit_review(
        self,
        owner: str,
        repo: str,
        number: int,
        review_id: Any,
        event: str = "COMMENT",
    ) -> Dict[str, Any]:
        """Submit a pending review, which is when its comments become visible."""
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{number}/reviews/{review_id}/events",
            json={"event": event},
        )

    def compare(
        self, owner: str, repo: str, base: str, head: str
    ) -> List[Dict[str, Any]]:''',
)

# --------------------------------------------------------------------------- #
# main.py: the context remembers the review it is writing into.
# --------------------------------------------------------------------------- #
main = replace(
    main,
    """    # Ids of the comments this run posted, in order. The retirement pass runs
    # right after the review and must not resolve a thread from this very list.
    posted_ids: List[int] = field(default_factory=list)""",
    """    # Ids of the comments this run posted, in order. The retirement pass runs
    # right after the review and must not resolve a thread from this very list.
    posted_ids: List[int] = field(default_factory=list)
    # The review this run's inline comments are collected into, and the comments
    # themselves — kept so that a submit which GitHub refuses can still post them
    # one by one instead of losing the run's findings.
    pending_review_id: Any = None
    pending_comments: List[Dict[str, Any]] = field(default_factory=list)""",
)

# --------------------------------------------------------------------------- #
# The tool posts into the pending review.
# --------------------------------------------------------------------------- #
main = replace(
    main,
    """    posted = post_inline_comments(
        ctx.gh, ctx.owner, ctx.repo, ctx.number, ctx.heads, normalized,
        posted_ids=ctx.posted_ids,
    )""",
    """    posted = post_inline_comments_pending(ctx, normalized)""",
)

# --------------------------------------------------------------------------- #
# The helpers, next to the posting function they extend.
# --------------------------------------------------------------------------- #
main = replace(
    main,
    """    log(f"Posted {posted}/{len(comments)} inline comment(s).")
    return posted
""",
    '''    log(f"Posted {posted}/{len(comments)} inline comment(s).")
    return posted


def _existing_pending_review(ctx: "ToolContext") -> Any:
    """The pending review an earlier run of this bot left behind, if any.

    A run that dies between its first comment and its submit leaves one, and
    GitHub allows only one pending review per user per pull request: without
    finding it, every later run would fail to start a review of its own. Reusing
    it also delivers what that run found.
    """
    try:
        for review in ctx.gh.list_reviews(ctx.owner, ctx.repo, ctx.number):
            if (review.get("state") or "").upper() != "PENDING":
                continue
            if is_bot_author(review.get("user")):
                return review.get("id")
    except Exception as exc:  # noqa: BLE001 - best effort
        log(f"Could not look for an earlier pending review: {exc}")
    return None


def pending_review_id(ctx: "ToolContext") -> Any:
    """This run's pending review, started on its first comment."""
    if ctx.pending_review_id is not None:
        return ctx.pending_review_id
    existing = _existing_pending_review(ctx)
    if existing is not None:
        log("Reusing the pending review an earlier run left on this pull request.")
        ctx.pending_review_id = existing
        return existing
    try:
        review = ctx.gh.create_pending_review(
            ctx.owner, ctx.repo, ctx.number, ctx.heads
        )
    except Exception as exc:  # noqa: BLE001 - post them the old way instead
        log(f"Warning: could not start a pending review ({exc}).")
        return None
    ctx.pending_review_id = (review or {}).get("id") if isinstance(review, dict) else None
    return ctx.pending_review_id


def post_inline_comments_pending(
    ctx: "ToolContext", comments: List[Dict[str, Any]]
) -> int:
    """Add comments to the review this run is writing, still pending.

    Nothing appears on the pull request until `submit_pending_review` — which is
    the whole point: a review that says six things is one review, not six.
    """
    if not comments:
        return 0
    if not ctx.heads:
        log("Warning: no commit id available; skipping inline comments.")
        return 0
    review_id = pending_review_id(ctx)
    if review_id is None:
        # No pending review to add to: a comment each is better than nothing.
        return post_inline_comments(
            ctx.gh, ctx.owner, ctx.repo, ctx.number, ctx.heads, comments,
            posted_ids=ctx.posted_ids,
        )
    added = 0
    for comment in comments:
        try:
            ctx.gh.add_review_comment(
                ctx.owner, ctx.repo, ctx.number, review_id, comment
            )
            ctx.pending_comments.append(comment)
            added += 1
        except Exception as exc:  # noqa: BLE001 - one bad comment, not the review
            log(
                "Warning: could not add the comment "
                f"({comment.get('path')}:{comment.get('line')}): {exc}"
            )
    log(f"Added {added}/{len(comments)} comment(s) to the pending review.")
    return added


def submit_pending_review(ctx: "ToolContext") -> int:
    """Submit what this run has been writing, and remember what it posted.

    The ids matter twice over: they are the count the log reports, and the
    retirement pass that runs next must not resolve a thread from this run's own
    findings. They are read from the submitted review, and from the pull request
    when GitHub answers without them.
    """
    review_id = ctx.pending_review_id
    if review_id is None:
        return 0
    ctx.pending_review_id = None
    try:
        submitted = ctx.gh.submit_review(
            ctx.owner, ctx.repo, ctx.number, review_id, "COMMENT"
        )
    except Exception as exc:  # noqa: BLE001 - a lost review beats a late one
        log(
            f"Warning: could not submit the review ({exc}); posting its comments "
            "one by one instead."
        )
        comments, ctx.pending_comments = ctx.pending_comments, []
        return post_inline_comments(
            ctx.gh, ctx.owner, ctx.repo, ctx.number, ctx.heads, comments,
            posted_ids=ctx.posted_ids,
        )
    comments = (submitted or {}).get("comments") or []
    if not comments:
        try:
            comments = [
                comment
                for comment in ctx.gh.list_review_comments(
                    ctx.owner, ctx.repo, ctx.number
                )
                if comment.get("pull_request_review_id") == review_id
            ]
        except Exception as exc:  # noqa: BLE001 - best effort
            log(f"Warning: could not read the submitted review's comments: {exc}")
    for comment in comments:
        comment_id = (comment or {}).get("id")
        if isinstance(comment_id, int):
            ctx.posted_ids.append(comment_id)
    log(
        f"Submitted one review carrying {len(ctx.pending_comments)} inline "
        "comment(s)."
    )
    ctx.pending_comments = []
    return len(comments)
''',
)

# --------------------------------------------------------------------------- #
# Both agent loops submit at the end.
# --------------------------------------------------------------------------- #
main = replace(
    main,
    """    # The model is not reliably willing to approve on its own, so act on the
    # verdict it declared at finish: anything still open blocks the approval.""",
    """    # One review, not one comment: everything this run added is still pending, and
    # this is where the author finally sees it.
    submit_pending_review(ctx)

    # The model is not reliably willing to approve on its own, so act on the
    # verdict it declared at finish: anything still open blocks the approval.""",
)

main = replace(
    main,
    """                ctx.reply_text = (answer.get("content") or "").strip()
                return ctx""",
    """                ctx.reply_text = (answer.get("content") or "").strip()
                submit_pending_review(ctx)
                return ctx""",
)

main = replace(
    main,
    """            if ctx.finish_requested:
                break

    return ctx""",
    """            if ctx.finish_requested:
                break

    submit_pending_review(ctx)
    return ctx""",
)

main = replace(main, 'VERSION = "2026-11-04.unity.141"', 'VERSION = "2026-11-04.unity.142"')

main_py.write_text(main, encoding="utf-8", newline="\n")
client_py.write_text(client, encoding="utf-8", newline="\n")
print("patched")
