from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\review\main.py")
t = p.read_text(encoding="utf-8")
old = 'VERSION = "2026-10-29.unity.136"'
new = 'VERSION = "2026-10-29.unity.137"'
assert t.count(old) == 1, t.count(old)
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("bumped")
