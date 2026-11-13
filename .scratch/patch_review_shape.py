import io
import sys

MAIN = r"E:\Gatongone\GitClone\ToolsWorkflow\review\main.py"
STATE = r"E:\Gatongone\GitClone\ToolsWorkflow\review\stage_state.py"

main = io.open(MAIN, encoding="utf-8").read()
state = io.open(STATE, encoding="utf-8").read()


def rep(old, new, count=1, where="main"):
    global main, state
    text = main if where == "main" else state
    if text.count(old) != count:
        sys.exit(f"[{where}] anchor found {text.count(old)} times: {old[:70]!r}")
    text = text.replace(old, new, count)
    if where == "main":
        main = text
    else:
        state = text


# --------------------------------------------------------------------------- #
# 1. No invented summary: a review body is text the run already has, or nothing.
# --------------------------------------------------------------------------- #
rep(
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
    '''def buffer_inline_comments(''',
)
rep(
    '''    if not body:
        body = review_summary_body(getattr(ctx.config, "language", ""), len(comments))
''',
    "",
)

# --------------------------------------------------------------------------- #
# 2. The review stage posts the build/test result as the review's body, and the
#    static stage's findings ride in the same review instead of arriving earlier
#    as comments of their own.
# --------------------------------------------------------------------------- #
rep(
    '''    block_approve: bool = False,
    block_reason: str = "Unity build or tests failed",
) -> Optional[ToolContext]:''',
    '''    block_approve: bool = False,
    block_reason: str = "Unity build or tests failed",
    review_body: str = "",
    carried_comments: Optional[List[Dict[str, Any]]] = None,
) -> Optional[ToolContext]:''',
)
rep(
    '''    ``block_approve`` forbids approval regardless of the model's verdict — used
    when compilation or tests failed — and ``block_reason`` is the sentence the
    log finishes that with. Returns the context when the model used tools, or
    ``None`` when it answered in prose instead — the caller then falls back to
    parsing that text.
    """''',
    '''    ``block_approve`` forbids approval regardless of the model's verdict — used
    when compilation or tests failed — and ``block_reason`` is the sentence the
    log finishes that with. ``review_body`` is what the review says above its
    comments — the build and test result, which is the one thing this run knows
    that the comments do not. ``carried_comments`` are findings another stage
    collected for this review (the static analysis), so that one review carries
    everything the run found rather than the analysis arriving first as comments
    of its own. Returns the context when the model used tools, or ``None`` when it
    answered in prose instead — the caller then falls back to parsing that text.
    """''',
)
rep(
    '''        block_approve=block_approve,
    )
    messages = agent_messages(system_prompt, session_records, turns)
    clear_leftover_pending_reviews(gh, owner, repo, number)''',
    '''        block_approve=block_approve,
    )
    ctx.buffered_comments.extend(carried_comments or [])
    if carried_comments:
        log(
            f"Carrying {len(carried_comments)} finding(s) from the static analysis "
            "into this review."
        )
    messages = agent_messages(system_prompt, session_records, turns)
    clear_leftover_pending_reviews(gh, owner, repo, number)''',
)
rep(
    '''    # One review, not one comment: everything this run added is still pending, and
    # this is where the author finally sees it.
    post_buffered_review(ctx)''',
    '''    # One review, not one comment: everything this run added is still pending, and
    # this is where the author finally sees it.
    post_buffered_review(ctx, review_body)''',
)

# The review stage hands both over.
rep(
    '''    ctx = run_agent_review(
        ai, gh, owner, repo, number, pr, files, system_prompt, records, turns, config,
        block_approve=build_blocked, block_reason=no_approve_reason,
    )''',
    '''    carried = _take_carried_comments(owner, repo, number, pr)
    ctx = run_agent_review(
        ai, gh, owner, repo, number, pr, files, system_prompt, records, turns, config,
        block_approve=build_blocked, block_reason=no_approve_reason,
        review_body=checks_state.extra_context if checks_state else "",
        carried_comments=carried,
    )''',
)

# Whatever the review step did not carry is posted before the stage ends.
rep(
    '''    return stage_review(gh, owner, repo, number, pr, config, event_name, payload)''',
    '''    code = stage_review(gh, owner, repo, number, pr, config, event_name, payload)
    _post_unclaimed_static_comments(gh, owner, repo, number, pr)
    return code''',
)

# --------------------------------------------------------------------------- #
# 3. The static stage collects its findings when a review will post them.
# --------------------------------------------------------------------------- #
rep(
    '''    clone_dir: Optional[str] = None,
    kind: Optional["repo_kind.Kind"] = None,
    unity: Optional["unity_runner.UnityResult"] = None,
) -> int:
    """Run ReSharper on the source and post findings inline.''',
    '''    clone_dir: Optional[str] = None,
    kind: Optional["repo_kind.Kind"] = None,
    unity: Optional["unity_runner.UnityResult"] = None,
    collector: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Run ReSharper on the source and post findings inline.

    ``collector`` hands the findings to the caller instead of posting them: the
    review step runs after this one and posts one review, so the analysis arriving
    first as comments of its own would be a second thing to read. It is used only
    when this run includes that step.''',
)
rep(
    '''    if config.dry_run:
        for c in normalized:
            print(f"[static] {c['path']}:{c['line']} {c['body']}")
        return len(normalized)
    return post_inline_comments(
        gh, owner, repo, number, pr.get("head", {}).get("sha", ""), normalized
    )''',
    '''    if config.dry_run:
        for c in normalized:
            print(f"[static] {c['path']}:{c['line']} {c['body']}")
        return len(normalized)
    if collector is not None:
        collector.extend(normalized)
        log(f"ReSharper: holding {len(normalized)} finding(s) for the review.")
        return len(normalized)
    return post_inline_comments(
        gh, owner, repo, number, pr.get("head", {}).get("sha", ""), normalized
    )''',
)
rep(
    '''    scope = _push_scope(gh, owner, repo, number, event_name, payload)
    posted = run_static_analysis(
        gh, owner, repo, number, pr, scope or files, config,
        clone_dir=state.clone_dir, kind=state.kind, unity=state.unity_result(),
    )
    if posted:
        log(f"Static analysis posted {posted} inline comment(s).")
    state.static_posted = posted
    stage_state.save(state, _state_path(owner, repo, number))
    return 0''',
    '''    scope = _push_scope(gh, owner, repo, number, event_name, payload)
    # The review step runs after this one in the same job, and posts one review.
    # When it is part of this run, the analysis is held for it; otherwise — a
    # `rebuild`, say, which runs the gates and nothing else — there is no review
    # to hold it for, so it posts itself.
    held: List[Dict[str, Any]] = []
    carried = "review" in _wanted_stages(event_name, payload)
    posted = run_static_analysis(
        gh, owner, repo, number, pr, scope or files, config,
        clone_dir=state.clone_dir, kind=state.kind, unity=state.unity_result(),
        collector=held if carried else None,
    )
    if posted:
        log(f"Static analysis posted {posted} inline comment(s).")
    state.static_posted = posted
    state.static_comments = held
    stage_state.save(state, _state_path(owner, repo, number))
    return 0''',
)

# --------------------------------------------------------------------------- #
# 4. Carrying the findings is a one-time claim, and anything unclaimed is posted.
# --------------------------------------------------------------------------- #
rep(
    '''def stage_review(''',
    '''def _take_carried_comments(
    owner: str, repo: str, number: int, pr: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """The static analysis's findings, claimed for this run's review.

    Claimed by clearing them from the state: a second review stage in the same job
    would otherwise post the same findings again.
    """
    path = _state_path(owner, repo, number)
    state = stage_state.load(path, pr.get("head", {}).get("sha", ""))
    if state is None or not state.static_comments:
        return []
    carried = list(state.static_comments)
    state.static_comments = []
    stage_state.save(state, path)
    return carried


def _post_unclaimed_static_comments(
    gh: GitHubClient, owner: str, repo: str, number: int, pr: Dict[str, Any]
) -> None:
    """Post findings the review step did not carry, so none of them is lost.

    The review step can end without a review — a `settle`, a review that answered
    in prose and failed, a model that posted nothing — and findings held for it
    must not disappear with it. One review again, not one comment each.
    """
    carried = _take_carried_comments(owner, repo, number, pr)
    if not carried:
        return
    head_sha = pr.get("head", {}).get("sha", "")
    if not head_sha:
        log("Warning: no commit id, so the static analysis's findings are dropped.")
        return
    try:
        gh.post_review(owner, repo, number, "", event="COMMENT", comments=carried)
        log(f"Posted {len(carried)} static-analysis finding(s) as one review.")
    except Exception as exc:  # noqa: BLE001 - the findings are worth one more try
        log(f"Warning: could not post the static analysis's findings ({exc}); "
            "posting them one by one instead.")
        post_inline_comments(gh, owner, repo, number, head_sha, carried)


def stage_review(''',
)

# --------------------------------------------------------------------------- #
# 5. `settle` says its result as the body of a review, not as a plain comment.
# --------------------------------------------------------------------------- #
rep(
    '''    after = unresolved_bot_thread_count(ctx.gh, ctx.owner, ctx.repo, ctx.number)
    ctx.gh.post_comment(
        ctx.owner, ctx.repo, ctx.number, settle_comment_body(before, after, outcome)
    )
    return 0''',
    '''    after = unresolved_bot_thread_count(ctx.gh, ctx.owner, ctx.repo, ctx.number)
    result = settle_comment_body(before, after, outcome)
    # A review, not an issue comment: the result is this run's verdict about the
    # pull request, and that is what a review's body is. When it approved, the
    # approval already carries the outcome, and a second review would be the same
    # answer twice.
    if outcome.approved:
        ctx.gh.post_comment(ctx.owner, ctx.repo, ctx.number, result)
        return 0
    try:
        ctx.gh.post_review(
            ctx.owner, ctx.repo, ctx.number, result, event="COMMENT"
        )
        log("Posted the settle result as a review.")
    except Exception as exc:  # noqa: BLE001 - the result must still be said
        log(f"Warning: could not post the settle result as a review ({exc}); "
            "posting it as a comment instead.")
        ctx.gh.post_comment(ctx.owner, ctx.repo, ctx.number, result)
    return 0''',
)

# --------------------------------------------------------------------------- #
# 6. The state carries the findings across the two stages.
# --------------------------------------------------------------------------- #
rep(
    '''    static_posted: int = 0
''',
    '''    static_posted: int = 0
    static_comments: List[Dict[str, Any]] = field(default_factory=list)
''',
    where="state",
)
rep(
    '''            "static_posted": self.static_posted,
''',
    '''            "static_posted": self.static_posted,
            "static_comments": list(self.static_comments),
''',
    where="state",
)
rep(
    '''            static_posted=int(data.get("static_posted") or 0),
''',
    '''            static_posted=int(data.get("static_posted") or 0),
            static_comments=[
                dict(c) for c in (data.get("static_comments") or []) if isinstance(c, dict)
            ],
''',
    where="state",
)

io.open(MAIN, "w", encoding="utf-8", newline="\n").write(main)
io.open(STATE, "w", encoding="utf-8", newline="\n").write(state)
print("patched")
