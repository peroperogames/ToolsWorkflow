from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\review\main.py")
t = p.read_text(encoding="utf-8")

old = """    if config.dry_run:
        for c in normalized:
            print(f"[static] {c['path']}:{c['line']} {c['body']}")
        return len(normalized)
    # One review, not one per finding: the batch is written into a pending review
    # and submitted once, so a pull request with fifteen inspection findings still
    # gets one review from the run.
    if config.dry_run:
        for c in normalized:
            print(f"[static] {c['path']}:{c['line']} {c['body']}")
        return len(normalized)
    return post_inline_comments("""
new = """    if config.dry_run:
        for c in normalized:
            print(f"[static] {c['path']}:{c['line']} {c['body']}")
        return len(normalized)
    return post_inline_comments("""
assert t.count(old) == 1, t.count(old)
t = t.replace(old, new)

old2 = """    ctx.inline_posted += posted
    return f"posted on {normalized[0]['path']}:{normalized[0]['line']}\""""
new2 = """    ctx.inline_posted += posted
    return f"added to the review: {normalized[0]['path']}:{normalized[0]['line']}\""""
assert t.count(old2) == 1, t.count(old2)
t = t.replace(old2, new2)
p.write_text(t, encoding="utf-8", newline="\n")
print("cleaned")
