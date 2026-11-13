from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\review\main.py")
t = p.read_text(encoding="utf-8")
pairs = [
    ("def pending_review_id(ctx: \"ToolContext\") -> Any:",
     "def _pending_review(ctx: \"ToolContext\") -> Any:"),
    ('    review_id = pending_review_id(ctx)\n    if review_id is None:\n        # No pending review to add to: a comment each is better than nothing.',
     '    review_id = _pending_review(ctx)\n    if review_id is None:\n        # No pending review to add to: a comment each is better than nothing.'),
    ("request\" — see `pending_review_id`, which reuses the leftover instead.",
     "request\" — see `_pending_review`, which reuses the leftover instead."),
]
for old, new in pairs:
    assert t.count(old) == 1, (old[:50], t.count(old))
    t = t.replace(old, new)
p.write_text(t, encoding="utf-8", newline="\n")
print("renamed")
