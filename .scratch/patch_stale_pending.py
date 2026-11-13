"""One-off: a pending review belongs to a commit, so never reuse a stale one.

RhythmAce-Neo #108: a run reused a pending review opened for an earlier commit, every
comment came back "404 Not Found", the model retried each one up to five times, the
64-step budget ran out with nothing posted and no verdict, and the approval after it
failed with 422 because that same review was still there.
"""

from pathlib import Path

root = Path(__file__).resolve().parent.parent
main_py = root / "review" / "main.py"
client_py = root / "review" / "github_client.py"

main = main_py.read_text(encoding="utf-8")
client = client_py.read_text(encoding="utf-8")


def replace(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, (text.count(old), old[:70])
    return text.replace(old, new)


# --------------------------------------------------------------------------- #
# github_client: a pending review can be deleted, and only a pending one.
# --------------------------------------------------------------------------- #
client = replace(
    client,
    """    def compare(
        self, owner: str, repo: str, base: str, head: str
    ) -> List[Dict[str, Any]]:""",
    '''    def delete_review(
        self, owner: str, repo: str, number: int, review_id: Any
    ) -> Any:
        """Delete a review — only a PENDING one; a submitted review is history."""
        return self._request(
            "DELETE",
            f"/repos/{owner}/{repo}/pulls/{number}/reviews/{review_id}",
        )

    def compare(
        self, owner: str, repo: str, base: str, head: str
    ) -> List[Dict[str, Any]]:''',
)

# --------------------------------------------------------------------------- #
# The pending-review helpers, rewritten around "a review belongs to a commit".
# --------------------------------------------------------------------------- #
start = main.index("def _existing_pending_review(")
end = main.index("def submit_pending_review(")
new_block = '''def _pending_reviews(
    gh: GitHubClient, owner: str, repo: str, number: int
) -> List[Dict[str, Any]]:
    """The bot's pending reviews on this pull request, oldest first as GitHub lists them."""
    try:
        return [
            review
            for review in gh.list_reviews(owner, repo, number)
            if (review.get("state") or "").upper() == "PENDING"
            and is_bot_author(review.get("user"))
        ]
    except Exception as exc:  # noqa: BLE001 - best effort
        log(f"Could not look for a pending review: {exc}")
        return []


def _delete_pending_review(
    gh: GitHubClient, owner: str, repo: str, number: int, review_id: Any
) -> None:
    """Throw a pending review away, comments and all."""
    if review_id is None:
        return
    try:
        gh.delete_review(owner, repo, number, review_id)
        log(f"Deleted the pending review {review_id}.")
    except Exception as exc:  # noqa: BLE001 - best effort
        log(f"Warning: could not delete the pending review {review_id}: {exc}")


def clear_stale_pending_reviews(
    gh: GitHubClient, owner: str, repo: str, number: int, head_sha: str
) -> int:
    """Delete pending reviews this bot left behind for an older commit.

    A pending review carries a commit, and its comments are validated against that
    commit's diff: a review opened before the head moved rejects every comment with
    "404 Not Found", and while it exists GitHub refuses both a new review and an
    approval (422). RhythmAce-Neo #108 is exactly that — a review from an earlier
    push, 64 steps of retries, nothing posted, no approval — so a run starts by
    clearing what it cannot use.
    """
    removed = 0
    for review in _pending_reviews(gh, owner, repo, number):
        if review.get("commit_id") == head_sha:
            continue
        _delete_pending_review(gh, owner, repo, number, review.get("id"))
        removed += 1
    if removed:
        log(
            f"Cleared {removed} pending review(s) left on an older commit; "
            "this run starts its own."
        )
    return removed


def _pending_review(
    gh: GitHubClient, owner: str, repo: str, number: int, commit_id: str
) -> Any:
    """The pull request's pending review for this commit, started on its first comment."""
    for review in _pending_reviews(gh, owner, repo, number):
        if review.get("commit_id") == commit_id:
            log("Reusing the pending review an earlier run left for this commit.")
            return review.get("id")
        # An older commit's review: its comments are validated against that commit,
        # so it would refuse every one of ours. GitHub allows only one pending
        # review per user, so it has to go before a new one can exist.
        _delete_pending_review(gh, owner, repo, number, review.get("id"))
    try:
        review = gh.create_pending_review(owner, repo, number, commit_id)
    except Exception as exc:  # noqa: BLE001 - post them the old way instead
        log(f"Warning: could not start a pending review ({exc}).")
        return None
    return (review or {}).get("id") if isinstance(review, dict) else None


def _post_comment_directly(
    gh: GitHubClient,
    owner: str,
    repo: str,
    number: int,
    commit_id: str,
    comment: Dict[str, Any],
    posted_ids: Optional[List[int]] = None,
) -> bool:
    """Post one comment on its own — the path a review that cannot take it falls back to."""
    try:
        created = gh.post_review_comment(owner, repo, number, commit_id, comment)
    except Exception as exc:  # noqa: BLE001
        log(
            "Warning: could not post the comment "
            f"({comment.get('path')}:{comment.get('line')}): {exc}"
        )
        return False
    comment_id = (created or {}).get("id")
    if posted_ids is not None and isinstance(comment_id, int):
        posted_ids.append(comment_id)
    return True


def add_comments_to_pending_review(
    gh: GitHubClient,
    owner: str,
    repo: str,
    number: int,
    commit_id: str,
    comments: List[Dict[str, Any]],
    review_id: Any = None,
    posted_ids: Optional[List[int]] = None,
) -> "Tuple[Any, List[Dict[str, Any]], int]":
    """Write comments into one pending review, invisible until it is submitted.

    Nothing appears on the pull request before that, which is the whole point: a
    review that says six things is one review, not six — one notification, one
    timeline entry, and nothing half-posted if the run dies.

    Returns ``(review_id, in_review, posted_directly)``. ``review_id`` is None when
    the review refused the comments and the rest went out one by one; a comment is
    never dropped because the carrier failed, and the caller stops trying the
    carrier instead of retrying it on every finding — a review that says 404 to
    every comment is a review that will say 404 to the next one too.
    """
    in_review: List[Dict[str, Any]] = []
    direct = 0
    if not comments:
        return review_id, in_review, direct
    if not commit_id:
        log("Warning: no commit id available; skipping inline comments.")
        return None, in_review, direct
    if review_id is None:
        review_id = _pending_review(gh, owner, repo, number, commit_id)
    if review_id is None:
        for comment in comments:
            if _post_comment_directly(
                gh, owner, repo, number, commit_id, comment, posted_ids
            ):
                direct += 1
        return None, in_review, direct
    for comment in comments:
        if review_id is None:
            if _post_comment_directly(
                gh, owner, repo, number, commit_id, comment, posted_ids
            ):
                direct += 1
            continue
        try:
            gh.add_review_comment(owner, repo, number, review_id, comment)
            in_review.append(comment)
        except Exception as exc:  # noqa: BLE001 - one bad comment, or a dead review
            log(
                "Warning: could not add the comment "
                f"({comment.get('path')}:{comment.get('line')}): {exc}"
            )
            review_id = None
            if _post_comment_directly(
                gh, owner, repo, number, commit_id, comment, posted_ids
            ):
                direct += 1
    if in_review:
        log(f"Added {len(in_review)}/{len(comments)} comment(s) to the pending review.")
    if direct:
        log(f"Posted {direct} comment(s) directly instead.")
    return review_id, in_review, direct


'''
main = main[:start] + new_block + main[end:]

# --------------------------------------------------------------------------- #
# The context remembers that the carrier died, so the run stops paying for it.
# --------------------------------------------------------------------------- #
main = replace(
    main,
    """    pending_review_id: Any = None
    pending_comments: List[Dict[str, Any]] = field(default_factory=list)""",
    """    pending_review_id: Any = None
    pending_comments: List[Dict[str, Any]] = field(default_factory=list)
    # The pending review refused a comment and was abandoned: the rest of the run
    # posts directly rather than retrying a carrier that has already said no.
    pending_broken: bool = False""",
)

# --------------------------------------------------------------------------- #
# The tool: no dedupe key for a comment that was not posted, and no dead carrier.
# --------------------------------------------------------------------------- #
main = replace(
    main,
    """    ctx.posted_comments.append(key)
    if ctx.config.dry_run:
        ctx.inline_posted += 1
        return f"dry-run: would post on {normalized[0]['path']}:{normalized[0]['line']}"
    review_id, added = add_comments_to_pending_review(
        ctx.gh, ctx.owner, ctx.repo, ctx.number, ctx.heads, normalized,
        review_id=ctx.pending_review_id,
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
    """    if ctx.config.dry_run:
        ctx.posted_comments.append(key)
        ctx.inline_posted += 1
        return f"dry-run: would post on {normalized[0]['path']}:{normalized[0]['line']}"
    if ctx.pending_broken:
        posted = post_inline_comments(
            ctx.gh, ctx.owner, ctx.repo, ctx.number, ctx.heads, normalized,
            posted_ids=ctx.posted_ids,
        )
    else:
        review_id, added, direct = add_comments_to_pending_review(
            ctx.gh, ctx.owner, ctx.repo, ctx.number, ctx.heads, normalized,
            review_id=ctx.pending_review_id, posted_ids=ctx.posted_ids,
        )
        ctx.pending_review_id = review_id
        ctx.pending_comments.extend(added)
        posted = len(added) + direct
        if review_id is None:
            _abandon_pending_review(ctx)
    if posted:
        # Only a comment that reached the pull request counts as said: recording the
        # key for one that failed makes the model's retry look like a duplicate, and
        # the run then rephrases the same finding instead of moving on.
        ctx.posted_comments.append(key)""",
)

# --------------------------------------------------------------------------- #
# Abandoning the carrier delivers what it already holds.
# --------------------------------------------------------------------------- #
main = replace(
    main,
    """def submit_this_run_review(ctx: "ToolContext") -> int:""",
    '''def _abandon_pending_review(ctx: "ToolContext") -> None:
    """Deliver what an unusable review already holds, then stop using it."""
    review_id, comments = ctx.pending_review_id, ctx.pending_comments
    ctx.pending_review_id, ctx.pending_comments = None, []
    ctx.pending_broken = True
    if review_id is None:
        return
    if not comments:
        _delete_pending_review(ctx.gh, ctx.owner, ctx.repo, ctx.number, review_id)
        return
    submit_pending_review(
        ctx.gh, ctx.owner, ctx.repo, ctx.number, ctx.heads, review_id, comments,
        ctx.posted_ids,
    )


def submit_this_run_review(ctx: "ToolContext") -> int:''',
)

# --------------------------------------------------------------------------- #
# Both agent loops clear what they cannot use before they post anything.
# --------------------------------------------------------------------------- #
main = replace(
    main,
    """    messages = agent_messages(system_prompt, session_records, turns)

    # Exclusive access to the session for the whole run; another job for the
    # same PR keeps working, just without persistence.""",
    """    messages = agent_messages(system_prompt, session_records, turns)
    clear_stale_pending_reviews(
        gh, owner, repo, number, pr.get("head", {}).get("sha", "")
    )

    # Exclusive access to the session for the whole run; another job for the
    # same PR keeps working, just without persistence.""",
)

main = replace(
    main,
    """    messages = agent_messages(system_prompt, session_records, turns)

    with session.hold(owner, repo, number) as store:
        if store:
            store.append(turns)
        for iteration in range(1, MAX_AGENT_ITERATIONS + 1):""",
    """    messages = agent_messages(system_prompt, session_records, turns)
    clear_stale_pending_reviews(
        gh, owner, repo, number, pr.get("head", {}).get("sha", "")
    )

    with session.hold(owner, repo, number) as store:
        if store:
            store.append(turns)
        for iteration in range(1, MAX_AGENT_ITERATIONS + 1):""",
)

# --------------------------------------------------------------------------- #
# The ReSharper batch uses the new return shape.
# --------------------------------------------------------------------------- #
main = replace(
    main,
    """    heads = pr.get("head", {}).get("sha", "")
    review_id, added = add_comments_to_pending_review(
        gh, owner, repo, number, heads, normalized
    )
    if review_id is None:
        return post_inline_comments(gh, owner, repo, number, heads, normalized)
    return submit_pending_review(
        gh, owner, repo, number, heads, review_id, added
    )""",
    """    heads = pr.get("head", {}).get("sha", "")
    review_id, in_review, direct = add_comments_to_pending_review(
        gh, owner, repo, number, heads, normalized
    )
    if review_id is not None and in_review:
        submit_pending_review(gh, owner, repo, number, heads, review_id, in_review)
    return len(in_review) + direct""",
)

main = replace(main, 'VERSION = "2026-11-04.unity.142"', 'VERSION = "2026-11-04.unity.143"')

main_py.write_text(main, encoding="utf-8", newline="\n")
client_py.write_text(client, encoding="utf-8", newline="\n")
print("patched")
