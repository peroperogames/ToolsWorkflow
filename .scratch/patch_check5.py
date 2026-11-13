from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_worker_tools.py")
t = p.read_text(encoding="utf-8")
old = 'numbered = re.search(r"^\\s*11: \\+public void Register", mine, re.M)'
new = 'numbered = re.search(r"^\\s*10: \\+public void Register", mine, re.M)'
assert t.count(old) == 1, t.count(old)
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("ok")
