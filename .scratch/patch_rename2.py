from pathlib import Path
root = Path(r"E:\Gatongone\GitClone\ToolsWorkflow")
main = root / "review" / "main.py"
client = root / "review" / "github_client.py"

t = main.read_text(encoding="utf-8")
pairs = [
    ('def pending_review_id(ctx: "ToolContext") -> Any:',
     'def _pending_review(ctx: "ToolContext") -> Any:'),
    ('    review_id = pending_review_id(ctx)',
     '    review_id = _pending_review(ctx)'),
]
for old, new in pairs:
    assert t.count(old) == 1, (old[:50], t.count(old))
    t = t.replace(old, new)
main.write_text(t, encoding="utf-8", newline="\n")

c = client.read_text(encoding="utf-8")
old = "pull request\" \u2014 see `pending_review_id`, which reuses the leftover instead."
new = "pull request\" \u2014 see `_pending_review` in main.py, which reuses the leftover."
assert c.count(old) == 1, c.count(old)
client.write_text(c.replace(old, new), encoding="utf-8", newline="\n")
print("renamed")
