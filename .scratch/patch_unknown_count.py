"""One-off: an unknown thread count must not be printed as -1."""

from pathlib import Path

path = Path(__file__).resolve().parent.parent / "review" / "main.py"
text = path.read_text(encoding="utf-8")


def replace(old: str, new: str) -> None:
    global text
    assert text.count(old) == 1, (text.count(old), old[:60])
    text = text.replace(old, new)


# `unresolved_bot_thread_count` answers -1 when the threads cannot be read.
replace(
    """        tail = (
            f"还有 {remaining} 个审查线程未解决，所以没有批准。"
            if remaining
            else "批准没有提交成功，运行日志里有原因。"
        )""",
    """        tail = (
            f"还有 {remaining} 个审查线程未解决，所以没有批准。"
            if remaining > 0
            else "批准没有提交成功，运行日志里有原因。"
        )""",
)

replace(
    """        tail = (
            f"{remaining} review thread(s) are still open, so it was not approved."
            if remaining
            else "The approval itself could not be submitted; the job log says why."
        )""",
    """        tail = (
            f"{remaining} review thread(s) are still open, so it was not approved."
            if remaining > 0
            else "The approval itself could not be submitted; the job log says why."
        )""",
)

replace(
    """    remaining = unresolved_bot_thread_count(gh, owner, repo, number)
    log(
        "Nothing to report and no approval to show it by"
        f" ({remaining} thread(s) open); saying so as a comment."
    )
    post_status_comment(
        gh, owner, repo, number,
        clean_verdict_body(ctx.config.language, remaining, approved=False),
        marker=CLEAN_VERDICT_MARKER,
    )""",
    """    remaining = unresolved_bot_thread_count(gh, owner, repo, number)
    log(
        "Nothing to report and no approval to show it by"
        + (f" ({remaining} thread(s) open)" if remaining > 0 else "")
        + "; saying so as a comment."
    )
    post_status_comment(
        gh, owner, repo, number,
        clean_verdict_body(ctx.config.language, max(remaining, 0), approved=False),
        marker=CLEAN_VERDICT_MARKER,
    )""",
)

path.write_text(text, encoding="utf-8", newline="\n")
print("patched")
