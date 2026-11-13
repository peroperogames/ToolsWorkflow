import io
import sys

PATH = r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_code_change_edits.py"

with io.open(PATH, encoding="utf-8") as fh:
    source = fh.read()

old = '''# 14. When an edit is quoted outside the changed lines of a long file, the retry reads
#     the whole file — the lines it means are somewhere else in it.'''
new = '''# 14. A change outside the changed lines cannot be quoted from them: the first answer
#     guesses and fails, the retry reads the whole file and places the edit.'''
if source.count(old) != 1:
    sys.exit("comment anchor not found once")
source = source.replace(old, new)

old_wrong = '''wrong = (
    '{"message": "fix A", "files": [{"path": "Big.cs", "edits": '
    '[{"find": "public void A() { }", "replace": "public void A() => Bar();"}]}]}'
)'''
new_wrong = '''wrong = (
    '{"message": "fix A", "files": [{"path": "Big.cs", "edits": '
    '[{"find": "public void A() => Bar();", "replace": "public void A() => Qux();"}]}]}'
)'''
if source.count(old_wrong) != 1:
    sys.exit("wrong-answer anchor not found once")
source = source.replace(old_wrong, new_wrong)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(source)
print("patched")
