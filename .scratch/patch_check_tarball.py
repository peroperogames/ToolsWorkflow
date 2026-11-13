from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_publish_workflow.py")
t = p.read_text(encoding="utf-8")
old = 'elif "npm publish \\"$tarball\\"" not in npmjs_body:'
new = 'elif \'tarball="$(pwd)/${tarball}"\' not in npmjs_body:\n    bad("the tarball path is relative, which npm reads as the GitHub shorthand owner/repo")\nelif "npm publish \\"$tarball\\"" not in npmjs_body:'
assert t.count(old) == 1, t.count(old)
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("check patched")
