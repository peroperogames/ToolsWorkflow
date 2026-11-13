from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\patch_buffer_review.py")
t = p.read_text(encoding="utf-8")
old = '''# The leftover cleanup replaces the stale-commit one.
main = replace(
    main,
    """    clear_stale_pending_reviews(
        gh, owner, repo, number, pr.get("head", {}).get("sha", "")
    )""",
    """    clear_leftover_pending_reviews(gh, owner, repo, number)""",
)'''
new = '''# The leftover cleanup replaces the stale-commit one (in both agent loops).
main = main.replace(
    """    clear_stale_pending_reviews(
        gh, owner, repo, number, pr.get("head", {}).get("sha", "")
    )""",
    """    clear_leftover_pending_reviews(gh, owner, repo, number)""",
)
assert "clear_stale_pending_reviews" not in main, "a call to the removed helper is left"'''
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
