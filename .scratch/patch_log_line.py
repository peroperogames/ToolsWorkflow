from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\review\main.py")
t = p.read_text(encoding="utf-8")
old = '''            log("The answer was cut off before the JSON ended; asking again, smaller.")'''
new = '''            log("The answer was cut off before the JSON ended; asking again for edits only.")'''
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
