from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_publish_workflow.py")
t = p.read_text(encoding="utf-8")

old = '''elif "PACKAGE_DIR" not in str(copy.get("env", {})):
    bad("the README copy does not know which directory the package is in")'''
new = '''elif "PACKAGE_DIR" not in str(copy.get("run") or "") and "PACKAGE_DIR" not in str(copy.get("env", {})):
    bad("the README copy does not know which directory the package is in")'''
assert t.count(old) == 1
t = t.replace(old, new)

old2 = '''if "${{ inputs.working-directory }}" in resolve_body:
    ok("the working-directory input is only a hint")
else:
    bad("the resolve step ignores the caller's working-directory")'''
new2 = '''if "${{ inputs.working-directory }}" in str(resolve_step.get("env") or {}):
    ok("the working-directory input is only a hint")
else:
    bad("the resolve step ignores the caller's working-directory")'''
assert t.count(old2) == 1
t = t.replace(old2, new2)
p.write_text(t, encoding="utf-8", newline="\n")
print("patched")
