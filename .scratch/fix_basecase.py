from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_resolve_step.sh")
t = p.read_text(encoding="utf-8")
old = """# A base tag keeps PeroNPM and drops the rest, whatever the caller asked for.
out=$(cd /e/Gatongone/GitClone/CITest && env \\"""
new = """# A base tag keeps PeroNPM and drops the rest, whatever the caller asked for.
: > "$work/env-base.txt"; : > "$work/out-base.txt"
out=$(cd /e/Gatongone/GitClone/CITest && env \\"""
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
