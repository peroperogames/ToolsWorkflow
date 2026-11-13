from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_pending_review.py")
t = p.read_text(encoding="utf-8")
t = t.replace("main.submit_pending_review(ctx)", "main.submit_this_run_review(ctx)")
p.write_text(t, encoding="utf-8", newline="\n")
print("patched")
