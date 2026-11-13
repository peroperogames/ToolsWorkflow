"""One-off: the run's own pending review is passed down, not looked up per comment."""

from pathlib import Path

main_py = Path(__file__).resolve().parent.parent / "review" / "main.py"
text = main_py.read_text(encoding="utf-8")


def replace(old: str, new: str) -> None:
    global text
    assert text.count(old) == 1, (text.count(old), old[:70])
    text = text.replace(old, new)


replace(
    """def add_comments_to_pending_review(
    gh: GitHubClient,
    owner: str,
    repo: str,
    number: int,
    commit_id: str,
    comments: List[Dict[str, Any]],
) -> "Tuple[Any, List[Dict[str, Any]]]":""",
    """def add_comments_to_pending_review(
    gh: GitHubClient,
    owner: str,
    repo: str,
    number: int,
    commit_id: str,
    comments: List[Dict[str, Any]],
    review_id: Any = None,
) -> "Tuple[Any, List[Dict[str, Any]]]":""",
)

replace(
    """    Returns the review's id and the comments actually added. The id is None when
    there is no review to add to (it could not be started, or there is no commit to
    anchor to), and the caller posts them the old way instead.
    \"\"\"""",
    """    Returns the review's id and the comments actually added. The id is None when
    there is no review to add to (it could not be started, or there is no commit to
    anchor to), and the caller posts them the old way instead.

    ``review_id`` is the review an agent run already opened: without it every
    comment would look the review up again — one listing per comment, and, worse,
    a second create if GitHub's listing lagged behind the first.
    \"\"\"""",
)

replace(
    """    review_id = _pending_review(gh, owner, repo, number, commit_id)
    if review_id is None:
        return None, added""",
    """    if review_id is None:
        review_id = _pending_review(gh, owner, repo, number, commit_id)
    if review_id is None:
        return None, added""",
)

replace(
    """    review_id, added = add_comments_to_pending_review(
        ctx.gh, ctx.owner, ctx.repo, ctx.number, ctx.heads, normalized
    )""",
    """    review_id, added = add_comments_to_pending_review(
        ctx.gh, ctx.owner, ctx.repo, ctx.number, ctx.heads, normalized,
        review_id=ctx.pending_review_id,
    )""",
)

main_py.write_text(text, encoding="utf-8", newline="\n")
print("patched")
