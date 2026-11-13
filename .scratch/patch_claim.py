import io
import sys

PATH = r"E:\Gatongone\GitClone\ToolsWorkflow\review\main.py"
main = io.open(PATH, encoding="utf-8").read()


def rep(old, new, count=1):
    global main
    if main.count(old) != count:
        sys.exit(f"anchor found {main.count(old)} times: {old[:70]!r}")
    main = main.replace(old, new, count)


# Claiming by clearing would lose the findings if the review died before posting
# them; read them, clear them only once the review carrying them went out.
rep(
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
''',
    '''def _read_static_comments(
    owner: str, repo: str, number: int, pr: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """The static analysis's findings, held for the review step to carry."""
    state = stage_state.load(
        _state_path(owner, repo, number), pr.get("head", {}).get("sha", "")
    )
    return list(state.static_comments) if state is not None else []


def _clear_static_comments(
    owner: str, repo: str, number: int, pr: Dict[str, Any]
) -> None:
    """Forget the held findings, once a review has carried them."""
    path = _state_path(owner, repo, number)
    state = stage_state.load(path, pr.get("head", {}).get("sha", ""))
    if state is None or not state.static_comments:
        return
    state.static_comments = []
    stage_state.save(state, path)
''',
)
rep(
    '''    carried = _take_carried_comments(owner, repo, number, pr)
    ctx = run_agent_review(''',
    '''    carried = _read_static_comments(owner, repo, number, pr)
    ctx = run_agent_review(''',
)
rep(
    '''    carried = _take_carried_comments(owner, repo, number, pr)
    if not carried:
        return
    head_sha = pr.get("head", {}).get("sha", "")''',
    '''    carried = _read_static_comments(owner, repo, number, pr)
    if not carried:
        return
    head_sha = pr.get("head", {}).get("sha", "")''',
)
rep(
    '''        gh.post_review(owner, repo, number, "", event="COMMENT", comments=carried)
        log(f"Posted {len(carried)} static-analysis finding(s) as one review.")
    except Exception as exc:  # noqa: BLE001 - the findings are worth one more try
        log(f"Warning: could not post the static analysis's findings ({exc}); "
            "posting them one by one instead.")
        post_inline_comments(gh, owner, repo, number, head_sha, carried)''',
    '''        gh.post_review(owner, repo, number, "", event="COMMENT", comments=carried)
        log(f"Posted {len(carried)} static-analysis finding(s) as one review.")
    except Exception as exc:  # noqa: BLE001 - the findings are worth one more try
        log(f"Warning: could not post the static analysis's findings ({exc}); "
            "posting them one by one instead.")
        post_inline_comments(gh, owner, repo, number, head_sha, carried)
    _clear_static_comments(owner, repo, number, pr)''',
)
rep(
    '''    post_buffered_review(ctx, review_body)
''',
    '''    post_buffered_review(ctx, review_body)
    # The findings the static analysis held are in that review (or in the one the
    # fallback posted); keeping them would post them again on the next stage.
    _clear_static_comments(owner, repo, number, pr)
''',
)

io.open(PATH, "w", encoding="utf-8", newline="\n").write(main)
print("patched")
