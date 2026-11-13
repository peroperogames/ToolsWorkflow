import io
import sys

PATH = r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_code_change_edits.py"

with io.open(PATH, encoding="utf-8") as fh:
    source = fh.read()

old = '''    def list_files(self, owner, repo, number):
        return [{"filename": path} for path in self.files]
'''
new = '''    patches = {}

    def list_files(self, owner, repo, number):
        return [
            {"filename": path, "patch": self.patches.get(path, "")}
            for path in self.files
        ]
'''
if source.count(old) != 1:
    sys.exit("fake anchor not found once")
source = source.replace(old, new)

anchor = 'print()\nif failures:'
addition = '''# 14. When an edit is quoted outside the changed lines of a long file, the retry reads
#     the whole file — the lines it means are somewhere else in it.
big_body = "\\n".join(f"// filler {i}" for i in range(1, 6001)) + "\\npublic void A() { }\\n"
big_patch = "@@ -1,2 +1,3 @@\\n // filler 1\\n // filler 2\\n+// changed\\n"
wrong = (
    '{"message": "fix A", "files": [{"path": "Big.cs", "edits": '
    '[{"find": "public void A() { }", "replace": "public void A() => Bar();"}]}]}'
)
right = (
    '{"message": "fix A", "files": [{"path": "Big.cs", "edits": '
    '[{"find": "public void A() { }", "replace": "public void A() => Baz();"}]}]}'
)
gh = GitHub({"Big.cs": big_body})
gh.patches = {"Big.cs": big_patch}
ai = AI([
    {"content": wrong, "finish_reason": "stop"},
    {"content": right, "finish_reason": "stop"},
])
run(ai, gh)
if (
    ai.calls == 2
    and "```diff" in ai.prompts[0]
    and "// filler 1" in ai.prompts[1]
    and gh.puts
    and "Baz()" in gh.puts[0][1]
):
    ok("an edit outside the changed lines makes the retry read the whole file")
else:
    bad(
        f"calls={ai.calls} first_diff={'```diff' in ai.prompts[0]} "
        f"second_whole={'// filler 1' in ai.prompts[1]} puts={gh.puts!r}"
    )

'''
if source.count(anchor) != 1:
    sys.exit("summary anchor not found once")
source = source.replace(anchor, addition + anchor)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(source)
print("patched")
