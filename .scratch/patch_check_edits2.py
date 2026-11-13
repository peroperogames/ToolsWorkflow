from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_code_change_edits.py")
t = p.read_text(encoding="utf-8")

# The fake AI keeps the messages so a retry can be inspected.
old = '''class AI:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def chat_message(self, messages, temperature=0.3, max_tokens=None, tools=None):
        self.calls += 1
        return self.answers.pop(0)'''
new = '''class AI:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0
        self.prompts = []

    def chat_message(self, messages, temperature=0.3, max_tokens=None, tools=None):
        self.calls += 1
        self.prompts.append(messages[-1]["content"])
        return self.answers.pop(0)'''
assert t.count(old) == 1
t = t.replace(old, new)

# Case 8: an edit that cannot be placed now asks again; two of them post one comment.
old = '''# 8. An edit that cannot be placed opens no branch and says which file.
answer = (
    '{"message": "fix A", "files": [{"path": "Foo.cs", "edits": '
    '[{"find": "not in the file", "replace": "x"}]}]}'
)
gh = GitHub({"Foo.cs": SOURCE})
ai = AI([{"content": answer, "finish_reason": "stop"}])
run(ai, gh)
if not gh.branches and not gh.prs and any("Foo.cs" in c for c in gh.comments):
    ok("an edit that cannot be placed opens no branch and names the file")
else:
    bad(f"branches={gh.branches!r} prs={gh.prs!r} comments={gh.comments!r}")'''
new = '''# 8. An edit that cannot be placed asks again, and two of them open nothing and name
#    the file.
answer = (
    '{"message": "fix A", "files": [{"path": "Foo.cs", "edits": '
    '[{"find": "not in the file", "replace": "x"}]}]}'
)
gh = GitHub({"Foo.cs": SOURCE})
ai = AI([
    {"content": answer, "finish_reason": "stop"},
    {"content": answer, "finish_reason": "stop"},
])
run(ai, gh)
if (
    ai.calls == 2
    and "could not be used" in ai.prompts[1]
    and not gh.branches
    and not gh.prs
    and any("Foo.cs" in c for c in gh.comments)
):
    ok("an edit that cannot be placed is asked again, then opens nothing and names the file")
else:
    bad(f"calls={ai.calls} branches={gh.branches!r} comments={gh.comments!r}")

# 8b. And the second answer is used when it can be applied.
second_answer = (
    '{"message": "fix A", "files": [{"path": "Foo.cs", "edits": '
    '[{"find": "    public void A() { }", "replace": "    public void A() => Bar();"}]}]}'
)
gh = GitHub({"Foo.cs": SOURCE})
ai = AI([
    {"content": answer, "finish_reason": "stop"},
    {"content": second_answer, "finish_reason": "stop"},
])
run(ai, gh)
if gh.puts and "Bar" in gh.puts[0][1] and gh.prs:
    ok("the retry after an unapplicable edit is what gets committed")
else:
    bad(f"puts={gh.puts!r} comments={gh.comments!r}")

# 8c. Whitespace the model got wrong is not a reason to give up.
answer_ws = (
    '{"message": "fix A", "files": [{"path": "Foo.cs", "edits": '
    '[{"find": "\\tpublic void A() { }  ", "replace": "    public void A() => Bar();"}]}]}'
)
gh = GitHub({"Foo.cs": SOURCE})
ai = AI([{"content": answer_ws, "finish_reason": "stop"}])
run(ai, gh)
if gh.puts and "Bar" in gh.puts[0][1] and ai.calls == 1:
    ok("an edit that differs only in whitespace applies on the first attempt")
else:
    bad(f"calls={ai.calls} puts={gh.puts!r}")'''
assert t.count(old) == 1
t = t.replace(old, new)

# Case 10: two cut-off answers still post one comment.
old2 = '''gh = GitHub({"Foo.cs": SOURCE})
ai = AI([
    {"content": first, "finish_reason": "length"},
    {"content": first, "finish_reason": "length"},
])'''
new2 = '''gh = GitHub({"Foo.cs": SOURCE})
ai = AI([
    {"content": first, "finish_reason": "length"},
    {"content": first, "finish_reason": "length"},
])'''
assert t.count(old2) == 1
p.write_text(t, encoding="utf-8", newline="\n")
print("check patched")
