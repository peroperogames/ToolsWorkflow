from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_publish_workflow.py")
t = p.read_text(encoding="utf-8")
old = 'declared = workflow[True]["workflow_call"]["secrets"].get("NPMJS_BOOTSTRAP_TOKEN") or {}'
new = 'declared = secrets.get("NPMJS_BOOTSTRAP_TOKEN") or {}'
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
