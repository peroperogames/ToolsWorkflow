from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\patch_reply_dismissal.py")
t = p.read_text(encoding="utf-8")
old = """replace('VERSION = "2026-11-04.unity.139"', 'VERSION = "2026-11-06.unity.140"')"""
new = """replace('VERSION = "2026-11-04.unity.140"', 'VERSION = "2026-11-04.unity.141"')"""
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
