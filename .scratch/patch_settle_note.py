from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\review\main.py")
t = p.read_text(encoding="utf-8")
old = """    outcome.approved = approve_if_clean(
        gh, owner, repo, number,
        pr.get("head", {}).get("sha", ""),
        "\u6240\u6709\u9057\u7559\u95ee\u9898\u5df2\u89e3\u51b3 \u2705",
    )
    return outcome
"""
new = """    outcome.approved = approve_if_clean(
        gh, owner, repo, number,
        pr.get("head", {}).get("sha", ""),
        "\u6240\u6709\u9057\u7559\u95ee\u9898\u5df2\u89e3\u51b3 \u2705",
    )
    if outcome.approved:
        # An earlier clean review may have said, in a comment, that it could not
        # approve. The approval makes that sentence wrong.
        update_standing_comment(
            gh, owner, repo, number,
            clean_verdict_body(language, 0, approved=True),
            CLEAN_VERDICT_MARKER,
        )
    return outcome
"""
assert t.count(old) == 1, t.count(old)
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
