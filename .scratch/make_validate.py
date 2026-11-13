from pathlib import Path
src = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.github\workflows\publish-npm.yml")
dst = Path(r"E:\Gatongone\GitClone\CITest\.github\workflows\validate.yml")
text = src.read_text(encoding="utf-8")
# The same file, with a trigger that can be dispatched: GitHub parses a workflow when it
# is pushed and lists it only when it is valid.
old = "on:\n  workflow_call:"
new = "on:\n  workflow_dispatch:\n  workflow_call:"
assert text.count(old) == 1
dst.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
print("written", dst)
