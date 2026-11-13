from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_reply_approve.py")
t = p.read_text(encoding="utf-8")

old = 'print("dry-run and no reply context -> nothing happens")\nprint("OK")'
new = '''print("dry-run and no reply context -> nothing happens")

# --- the `approve` tool: it approves, or names what blocks it, and never claims a
# permission it cannot see. RhythmAce-Neo #108 answered "我没有提交 approve 的权限"
# one minute before the bot approved that same pull request.
main.update_standing_comment = lambda *a, **k: False
main.clean_verdict_body = lambda *a, **k: "body"
main.CLEAN_VERDICT_MARKER = "<!-- marker -->"


def approve_ctx():
    value = main.ToolContext(
        gh=types.SimpleNamespace(), owner="o", repo="r", number=3, pr=pr, files=[],
        config=config, heads="abc123",
    )
    return value


main.already_approved = lambda *a, **k: False
main.unresolved_bot_thread_count = lambda *a, **k: 0
main.approve_if_clean = lambda *a, **k: True
value = approve_ctx()
answer = main._tool_approve({}, value)
assert value.approved and answer.startswith("approved"), (answer, value.approved)
print("asked to approve with nothing open -> it approves")

main.approve_if_clean = lambda *a, **k: False
main.unresolved_bot_thread_count = lambda *a, **k: 3
answer = main._tool_approve({}, approve_ctx())
assert "3 review thread(s)" in answer, answer
assert "权限" not in answer and "permission" not in answer.lower(), answer
print("three threads open -> it names them, and does not invent a permission")

main.already_approved = lambda *a, **k: True
main.unresolved_bot_thread_count = lambda *a, **k: 0
answer = main._tool_approve({}, approve_ctx())
assert "already" in answer, answer
print("a commit that is already approved is not approved again")

dry_value = main.ToolContext(
    gh=types.SimpleNamespace(), owner="o", repo="r", number=3, pr=pr, files=[],
    config=types.SimpleNamespace(dry_run=True, language="cn"), heads="abc123",
)
assert main._tool_approve({}, dry_value).startswith("dry-run"), "dry run must not approve"
print("a dry run says what it would do and approves nothing")
print("OK")'''
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
