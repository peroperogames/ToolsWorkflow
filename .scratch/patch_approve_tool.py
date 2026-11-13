"""One-off: reply mode can approve when asked, instead of inventing a reason it cannot.

RhythmAce-Neo #108: the bot approved, and a minute earlier it had answered "我没有提交
approve 的权限，审批只能由有写权限的账号来完成" — a claim about the installation that
nothing in the run checked. The reply agent has no approve tool, so it reached for the
one explanation a model reaches for.
"""

from pathlib import Path

root = Path(__file__).resolve().parent.parent
main_py = root / "review" / "main.py"
main = main_py.read_text(encoding="utf-8")


def replace(old: str, new: str) -> None:
    global main
    assert main.count(old) == 1, (main.count(old), old[:70])
    main = main.replace(old, new)


# 1. The tool the developer's request actually needs.
replace(
    '''REPLY_TOOLS.append(
    {
        "type": "function",
        "function": {
            "name": "finish",''',
    '''REPLY_TOOLS.append(
    {
        "type": "function",
        "function": {
            "name": "approve",
            "description": (
                "Approve the pull request when the developer asks for it. It goes "
                "through only if no review thread is open and this commit is not "
                "approved already; the answer says which one stopped it."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }
)

REPLY_TOOLS.append(
    {
        "type": "function",
        "function": {
            "name": "finish",''',
)

# 2. The handler: the same guard the pipeline uses, and a sentence that is true.
replace(
    '''def _tool_finish_reply(args: Dict[str, Any], ctx: ToolContext) -> str:''',
    '''def _tool_approve(args: Dict[str, Any], ctx: ToolContext) -> str:
    """Approve the pull request, or say exactly what is in the way.

    The approval goes through the same gate as the pipeline's own: nothing may be
    left open, and a commit that is already approved is not approved again. What it
    never does is explain a refusal with a permission it cannot see — the reply that
    prompted this said the bot had no write access, one minute before the bot
    approved the very same pull request.
    """
    if ctx.approved:
        return "approved: this run already submitted the approval."
    if ctx.config.dry_run:
        return "dry-run: would approve."
    head_sha = ctx.pr.get("head", {}).get("sha", "")
    if approve_if_clean(
        ctx.gh, ctx.owner, ctx.repo, ctx.number, head_sha, "审查通过，无遗留问题 ✅"
    ):
        ctx.approved = True
        # A standing comment saying "could not approve" is now wrong.
        update_standing_comment(
            ctx.gh, ctx.owner, ctx.repo, ctx.number,
            clean_verdict_body(ctx.config.language, 0, approved=True),
            CLEAN_VERDICT_MARKER,
        )
        return "approved: the pull request is approved."
    if already_approved(ctx.gh, ctx.owner, ctx.repo, ctx.number, head_sha):
        return "nothing to do: this commit already carries an approval."
    remaining = unresolved_bot_thread_count(ctx.gh, ctx.owner, ctx.repo, ctx.number)
    if remaining > 0:
        return (
            f"not approved: {remaining} review thread(s) are still open. Resolve "
            "them with resolve_thread, or ask the author to, and ask again."
        )
    return "not approved: GitHub refused the approval; the run log says why."


def _tool_finish_reply(args: Dict[str, Any], ctx: ToolContext) -> str:''',
)

# 3. Register it.
replace(
    '''    "finish": _tool_finish,
}''',
    '''    "finish": _tool_finish,
    "approve": _tool_approve,
}''',
)

# 4. The reply prompt: use the tool, and never invent a permission.
replace(
    '''    "When the developer dismisses a finding — \\"ignore it\\", \\"wrong\\", \\"by ''',
    '''    "When the developer asks you to approve the pull request, call `approve` — not a "
    "sentence about what you are allowed to do. It approves when nothing is open and "
    "says what stopped it otherwise. Never explain a refusal with a permission, a "
    "role or a capability you cannot see: this bot's writes are the pipeline's, and "
    "the reply that said it had no approval rights went out a minute before the bot "
    "approved that pull request.\\n"
    "Do not state the build or test status unless this run was given it — \\"the "
    "tests pass\\" is a fact about a run, not about the code.\\n"
    "When the developer dismisses a finding — \\"ignore it\\", \\"wrong\\", \\"by ''',
)

replace('VERSION = "2026-11-04.unity.144"', 'VERSION = "2026-11-04.unity.145"')

main_py.write_text(main, encoding="utf-8", newline="\n")
print("patched")
