"""One-off: buffer the findings and submit them as one review, the supported way.

`POST /pulls/{n}/reviews/{id}/comments` does not exist — GitHub answers 404 — so a
pending review can never be added to after it is opened. What the API does support is
one review carrying many comments: `POST /pulls/{n}/reviews` with a `comments` array.
That is the same shape the prose fallback has always used and it gives exactly the
behaviour that was asked for: nothing visible until the run has finished deciding what
to say, then one review.
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
# The error message keeps what GitHub said about it, not just "Validation Failed".
# --------------------------------------------------------------------------- #
client = replace(
    client,
    """        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("message", "")
            except ValueError:
                detail = resp.text
            raise RuntimeError(
                f"GitHub API error ({resp.status_code}) {method} {path}: {detail}"
            )""",
    """        if resp.status_code >= 400:
            detail = ""
            try:
                body = resp.json()
                detail = body.get("message", "")
                # "Validation Failed" alone says nothing: the reason is in `errors`,
                # and a comment GitHub rejects cannot be repaired without it.
                errors = body.get("errors")
                if errors:
                    detail = f"{detail} {errors}" if detail else str(errors)
            except ValueError:
                detail = resp.text
            raise RuntimeError(
                f"GitHub API error ({resp.status_code}) {method} {path}: {detail}"
            )""",
)

# The pending-review create/add/submit calls are gone; deleting one is still needed.
start = client.index("    def create_pending_review(")
end = client.index("    def compare(")
client = client[:start] + '''    def delete_review(
        self, owner: str, repo: str, number: int, review_id: Any
    ) -> Any:
        """Delete a review — only a PENDING one; a submitted review is history."""
        return self._request(
            "DELETE",
            f"/repos/{owner}/{repo}/pulls/{number}/reviews/{review_id}",
        )

''' + client[end:]

# --------------------------------------------------------------------------- #
# Replace every pending-review helper with the buffer.
# --------------------------------------------------------------------------- #
start = main.index("def _pending_reviews(")
end = main.index("def index_diff_lines(")
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


def clear_leftover_pending_reviews(
    gh: GitHubClient, owner: str, repo: str, number: int
) -> int:
    """Delete pending reviews this bot left behind.

    Nothing creates them any more — a run buffers its findings and posts one review —
    so one that exists is a leftover, and it is not harmless: GitHub refuses a new
    review or an approval while a pending one is there (422). RhythmAce-Neo #108 had
    one, and it is why that pull request's approval failed as well.
    """
    removed = 0
    for review in _pending_reviews(gh, owner, repo, number):
        try:
            gh.delete_review(owner, repo, number, review.get("id"))
            removed += 1
        except Exception as exc:  # noqa: BLE001 - best effort
            log(
                "Warning: could not delete the pending review "
                f"{review.get('id')}: {exc}"
            )
    if removed:
        log(f"Deleted {removed} leftover pending review(s).")
    return removed


def buffer_inline_comments(
    ctx: "ToolContext", comments: List[Dict[str, Any]]
) -> int:
    """Hold the findings until the run knows everything it wants to say.

    Nothing reaches the pull request here. That is the point: a review still deciding
    what else to say must not show half of it, and the API has exactly one call that
    posts a review with all of its comments at once.
    """
    if not comments:
        return 0
    ctx.buffered_comments.extend(comments)
    log(f"Buffered {len(comments)} comment(s) for the review.")
    return len(comments)


def post_buffered_review(ctx: "ToolContext", body: str = "") -> int:
    """Post the findings this run buffered as one review.

    One call with the whole list is what the API supports, and it is the shape that
    makes "one review" true for the author: one notification, one timeline entry, and
    nothing on the diff while the reviewer is still reading.

    A review GitHub refuses falls back to posting the comments one by one — a lost
    review is worse than a noisy one — and either way the ids are recorded, because
    the retirement pass that runs next must not resolve this run's own findings.
    """
    comments, ctx.buffered_comments = ctx.buffered_comments, []
    if not comments:
        return 0
    if not ctx.heads:
        log("Warning: no commit id available; skipping the comments.")
        return 0
    try:
        review = ctx.gh.post_review(
            ctx.owner, ctx.repo, ctx.number, body, event="COMMENT", comments=comments
        )
    except Exception as exc:  # noqa: BLE001 - the findings must survive a refusal
        log(
            f"Warning: could not post the review ({exc}); "
            "posting its comments one by one instead."
        )
        return post_inline_comments(
            ctx.gh, ctx.owner, ctx.repo, ctx.number, ctx.heads, comments,
            posted_ids=ctx.posted_ids,
        )
    found = (review or {}).get("comments") or []
    if not found:
        try:
            review_id = (review or {}).get("id")
            found = [
                comment
                for comment in ctx.gh.list_review_comments(
                    ctx.owner, ctx.repo, ctx.number
                )
                if comment.get("pull_request_review_id") == review_id
            ]
        except Exception as exc:  # noqa: BLE001 - best effort
            log(f"Warning: could not read the posted review's comments: {exc}")
    for comment in found:
        comment_id = (comment or {}).get("id")
        if isinstance(comment_id, int):
            ctx.posted_ids.append(comment_id)
    log(f"Posted one review carrying {len(comments)} inline comment(s).")
    return len(comments)


'''
main = main[:start] + new_block + main[end:]

# The context buffers instead of holding a review.
main = replace(
    main,
    """    # The review this run's inline comments are collected into, and the comments
    # themselves — kept so that a submit which GitHub refuses can still post them
    # one by one instead of losing the run's findings.
    pending_review_id: Any = None
    pending_comments: List[Dict[str, Any]] = field(default_factory=list)
    # The pending review refused a comment and was abandoned: the rest of the run
    # posts directly rather than retrying a carrier that has already said no.
    pending_broken: bool = False""",
    """    # The findings this run has decided to report and not posted yet: they go out as
    # one review when the run is done, so the author never sees half a review.
    buffered_comments: List[Dict[str, Any]] = field(default_factory=list)""",
)

# The tool buffers, and says so.
main = replace(
    main,
    """    if ctx.pending_broken:
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
            _abandon_pending_review(ctx)""",
    """    posted = buffer_inline_comments(ctx, normalized)""",
)

# Both agent loops post the buffered review at the end.
main = main.replace("    submit_this_run_review(ctx)\n", "    post_buffered_review(ctx)\n")
main = main.replace(
    "                submit_this_run_review(ctx)\n", "                post_buffered_review(ctx)\n"
)

# The leftover cleanup replaces the stale-commit one (in both agent loops).
main = main.replace(
    """    clear_stale_pending_reviews(
        gh, owner, repo, number, pr.get("head", {}).get("sha", "")
    )""",
    """    clear_leftover_pending_reviews(gh, owner, repo, number)""",
)
assert "clear_stale_pending_reviews" not in main, "a call to the removed helper is left"

# The ReSharper batch keeps posting comment by comment (it has no agent to buffer).
main = replace(
    main,
    """    heads = pr.get("head", {}).get("sha", "")
    review_id, in_review, direct = add_comments_to_pending_review(
        gh, owner, repo, number, heads, normalized
    )
    if review_id is not None and in_review:
        submit_pending_review(gh, owner, repo, number, heads, review_id, in_review)
    return len(in_review) + direct""",
    """    if config.dry_run:
        for c in normalized:
            print(f"[static] {c['path']}:{c['line']} {c['body']}")
        return len(normalized)
    return post_inline_comments(
        gh, owner, repo, number, pr.get("head", {}).get("sha", ""), normalized
    )""",
)

main = replace(main, 'VERSION = "2026-11-04.unity.143"', 'VERSION = "2026-11-04.unity.144"')

main_py.write_text(main, encoding="utf-8", newline="\n")
client_py.write_text(client, encoding="utf-8", newline="\n")
print("patched")
