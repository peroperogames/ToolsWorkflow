from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\review\main.py")
t = p.read_text(encoding="utf-8")
old = """    elif retry:
    else:
        tail = "Generate the code changes as JSON.\""""
new = '''    elif retry:
        tail = (
            "The previous answer did not arrive as valid JSON — it was cut off "
            "before the object ended, because it was as long as the files rather "
            "than as long as the change. Answer again with `find`/`replace` edits: "
            "never a complete file, not even for a small one. Fewer files, fewer "
            "lines, and the same JSON shape. Return ONLY the JSON."
        )
    else:
        tail = "Generate the code changes as JSON."'''
assert t.count(old) == 1, t.count(old)
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("repaired")
