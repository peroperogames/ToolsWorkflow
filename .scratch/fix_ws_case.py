from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_code_change_edits.py")
t = p.read_text(encoding="utf-8")
old = '''    '[{"find": "\\tpublic void A() { }  ", "replace": "    public void A() => Bar();"}]}]}\''''
new = '''    '[{"find": "      public void A() { }   ", "replace": "    public void A() => Bar();"}]}]}\''''
assert t.count(old) == 1, t.count(old)
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
