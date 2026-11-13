import io
import sys

PATH = r"E:\Gatongone\GitClone\ToolsWorkflow\review\main.py"
main = io.open(PATH, encoding="utf-8").read()


def rep(old, new, count=1):
    global main
    if main.count(old) != count:
        sys.exit(f"anchor found {main.count(old)} times: {old[:70]!r}")
    main = main.replace(old, new, count)


# The command path builds the same review as a push does, so it has to hand over
# the same two things: the result that goes above the comments, and the findings
# the static step held for this review.
rep(
    '''        gates = resolve_checks(
            gh, owner, repo, number, pr, files, config, with_static=with_static
        )
        extra_context = gates.extra_context''',
    '''        gates = resolve_checks(
            gh, owner, repo, number, pr, files, config, with_static=with_static
        )
        # The build and test result is what the review says above its comments —
        # the paragraph a person would write there, already written by the run.
        review_body = gates.extra_context
        extra_context = gates.extra_context''',
)
rep(
    '''        extra_context = NO_GATES_STATUS
        may_approve = False''',
    '''        extra_context = NO_GATES_STATUS
        review_body = ""
        may_approve = False''',
)
rep(
    '''    ctx = run_agent_review(
        ai, gh, owner, repo, number, pr, files, system_prompt, session_records, turns,
        config, block_approve=not may_approve, block_reason=block_reason,
    )''',
    '''    ctx = run_agent_review(
        ai, gh, owner, repo, number, pr, files, system_prompt, session_records, turns,
        config, block_approve=not may_approve, block_reason=block_reason,
        review_body=review_body,
        carried_comments=_read_static_comments(owner, repo, number, pr),
    )''',
)

io.open(PATH, "w", encoding="utf-8", newline="\n").write(main)
print("patched")
