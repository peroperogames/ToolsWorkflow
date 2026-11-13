"""One-off: a clean review that cannot approve says so on the pull request.

RhythmAce-Neo #80: 14 agent steps, 0 inline comments, verdict=approve, three threads
still open -> nothing was posted anywhere, so the pull request showed no sign the
review had run at all.
"""

from pathlib import Path

path = Path(__file__).resolve().parent.parent / "review" / "main.py"
text = path.read_text(encoding="utf-8")


def replace(old: str, new: str) -> str:
    assert text.count(old) == 1, (text.count(old), old[:60])
    return text.replace(old, new)


# 1. The marker, beside the build status one.
text = replace(
    'BUILD_STATUS_MARKER = "<!-- ai-review build status -->"\n',
    'BUILD_STATUS_MARKER = "<!-- ai-review build status -->"\n'
    "# ... and the same for 'a review ran and found nothing', which otherwise leaves\n"
    "# no trace on the pull request when the approval it asks for is withheld.\n"
    'CLEAN_VERDICT_MARKER = "<!-- ai-review clean verdict -->"\n',
)

# 2. One place that finds the living comment, so the clean-verdict comment can be
#    updated without being posted.
text = replace(
    """    if marker:
        try:
            for comment in gh.list_comments(owner, repo, number):
                if marker not in (comment.get("body") or ""):
                    continue
                if not is_bot_author(comment.get("user")):
                    continue
                if gh.update_comment(owner, repo, comment.get("id"), body):
                    log("Updated the earlier status comment instead of adding another.")
                    return True
        except Exception as exc:  # noqa: BLE001 - fall back to posting
            log(f"Could not look for an earlier status comment: {exc}")
    try:
        gh.post_comment(owner, repo, number, body)
""",
    """    if marker:
        existing = standing_comment_id(gh, owner, repo, number, marker)
        if existing is not None and gh.update_comment(owner, repo, existing, body):
            log("Updated the earlier status comment instead of adding another.")
            return True
    try:
        gh.post_comment(owner, repo, number, body)
""",
)

# 3. The two helpers, just above post_status_comment.
text = replace(
    """def post_status_comment(
    gh: GitHubClient,
    owner: str,
    repo: str,
    number: int,
    body: str,
    marker: str = "",
) -> bool:
""",
    '''def standing_comment_id(
    gh: GitHubClient, owner: str, repo: str, number: int, marker: str
) -> Any:
    """The id of this bot's comment carrying ``marker``, or None.

    A status that describes the current state of a pull request must not stack one
    copy per run, so the marker in the body is how the next run finds the copy it is
    about to replace.
    """
    try:
        for comment in gh.list_comments(owner, repo, number):
            if marker in (comment.get("body") or "") and is_bot_author(
                comment.get("user")
            ):
                return comment.get("id")
    except Exception as exc:  # noqa: BLE001 - best effort
        log(f"Could not look for an earlier status comment: {exc}")
    return None


def update_standing_comment(
    gh: GitHubClient, owner: str, repo: str, number: int, body: str, marker: str
) -> bool:
    """Rewrite the comment carrying ``marker``, and post nothing when there is none.

    The difference from `post_status_comment` is what happens on a pull request that
    has never had the comment: here, nothing. Used where the comment is a statement
    that has since become wrong, and the only fix is to correct it in place.
    """
    existing = standing_comment_id(gh, owner, repo, number, marker)
    if existing is None:
        return False
    if gh.update_comment(owner, repo, existing, body):
        log("Updated the standing comment.")
        return True
    return False


def post_status_comment(
    gh: GitHubClient,
    owner: str,
    repo: str,
    number: int,
    body: str,
    marker: str = "",
) -> bool:
''',
)

# 4. The clean verdict: approve when it can, and say so when it cannot.
text = replace(
    '''def act_on_clean_verdict(
    gh: GitHubClient, owner: str, repo: str, number: int, ctx: ToolContext
) -> None:
    """Approve a review that came back clean, once nothing is left open."""
    if ctx.config.dry_run:
        log("dry-run: would approve")
        return
    head_sha = ctx.pr.get("head", {}).get("sha", "")
    if approve_if_clean(gh, owner, repo, number, head_sha, "审查通过，无遗留问题 ✅"):
        ctx.approved = True
''',
    '''def clean_verdict_body(language: str, remaining: int, approved: bool) -> str:
    """What a review that found nothing says when it cannot show an approval.

    No reason per thread: which ones are open is on the pull request itself, and this
    comment is one line saying the review ran.
    """
    chinese = "chinese" in resolve_language(language).lower()
    if approved:
        head = "本次审查没有发现新问题，已批准。" if chinese else (
            "This review found nothing new, and it is approved."
        )
        return head + "\\n\\n" + CLEAN_VERDICT_MARKER
    if chinese:
        head = "本次审查没有发现新问题。"
        tail = (
            f"还有 {remaining} 个审查线程未解决，所以没有批准。"
            if remaining
            else "批准没有提交成功，运行日志里有原因。"
        )
    else:
        head = "This review found nothing new."
        tail = (
            f"{remaining} review thread(s) are still open, so it was not approved."
            if remaining
            else "The approval itself could not be submitted; the job log says why."
        )
    return f"{head}\\n\\n{tail}\\n\\n{CLEAN_VERDICT_MARKER}"


def act_on_clean_verdict(
    gh: GitHubClient, owner: str, repo: str, number: int, ctx: ToolContext
) -> None:
    """Approve a review that came back clean, once nothing is left open."""
    if ctx.config.dry_run:
        log("dry-run: would approve")
        return
    head_sha = ctx.pr.get("head", {}).get("sha", "")
    if approve_if_clean(gh, owner, repo, number, head_sha, "审查通过，无遗留问题 ✅"):
        ctx.approved = True
        # A previous run may have said here that it could not approve. That sentence
        # is now wrong, and this is the one place that knows it.
        update_standing_comment(
            gh, owner, repo, number,
            clean_verdict_body(ctx.config.language, 0, approved=True),
            CLEAN_VERDICT_MARKER,
        )
        return
    if already_approved(gh, owner, repo, number, head_sha) or ctx.inline_posted:
        # The pull request already shows the outcome: an approval on this commit, or
        # the findings themselves.
        return
    remaining = unresolved_bot_thread_count(gh, owner, repo, number)
    log(
        "Nothing to report and no approval to show it by"
        f" ({remaining} thread(s) open); saying so as a comment."
    )
    post_status_comment(
        gh, owner, repo, number,
        clean_verdict_body(ctx.config.language, remaining, approved=False),
        marker=CLEAN_VERDICT_MARKER,
    )
''',
)

path.write_text(text, encoding="utf-8", newline="\n")
print("patched", path)
