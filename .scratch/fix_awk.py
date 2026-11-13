from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_resolve_step.sh")
t = p.read_text(encoding="utf-8")
old = """  capture && /^          / { sub(/^          /, ""); print; next }
  capture { exit }"""
new = """  capture && /^$/ { print ""; next }
  capture && /^          / { sub(/^          /, ""); print; next }
  capture { exit }"""
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
