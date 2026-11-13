from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\review\main.py")
t = p.read_text(encoding="utf-8")
pairs = [
    ('else "\u6279\u51c6\u6ca1\u6709\u63d0\u4ea4\u6210\u529f\uff0c\u8fd0\u884c\u65e5\u5fd7\u91cc\u6709\u539f\u56e0\u3002"',
     'else "\u6ca1\u6709\u6279\u51c6\uff1b\u8fd0\u884c\u65e5\u5fd7\u91cc\u6709\u539f\u56e0\u3002"'),
    ('else "The approval itself could not be submitted; the job log says why."',
     'else "It was not approved; the job log says why."'),
]
for old, new in pairs:
    assert t.count(old) == 1, (old, t.count(old))
    t = t.replace(old, new)
p.write_text(t, encoding="utf-8", newline="\n")
print("patched")
