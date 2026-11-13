import io

path = r"E:\Gatongone\GitClone\ToolsWorkflow\review\main.py"
source = io.open(path, encoding="utf-8").read()
old = 'VERSION = "2026-11-04.unity.146"'
new = 'VERSION = "2026-11-04.unity.147"'
if source.count(old) != 1:
    raise SystemExit("version anchor not found once")
io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
print("bumped to", new)
