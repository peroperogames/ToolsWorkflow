import io

p = r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\patch_review_shape.py"
s = io.open(p, encoding="utf-8").read()
old = """rep(
    '''    messages = agent_messages(system_prompt, session_records, turns)
    clear_leftover_pending_reviews(gh, owner, repo, number)''',
    '''    ctx.buffered_comments.extend(carried_comments or [])"""
new = """rep(
    '''        block_approve=block_approve,
    )
    messages = agent_messages(system_prompt, session_records, turns)
    clear_leftover_pending_reviews(gh, owner, repo, number)''',
    '''        block_approve=block_approve,
    )
    ctx.buffered_comments.extend(carried_comments or [])"""
if s.count(old) != 1:
    raise SystemExit(f"anchor {s.count(old)}")
io.open(p, "w", encoding="utf-8", newline="\n").write(s.replace(old, new, 1))
print("patched script")
