import sys, types
from pathlib import Path
sys.path.insert(0, str(Path(r"E:\Gatongone\GitClone\ToolsWorkflow") / "review"))
import main

class G:
    def __init__(self): self.comments=[]; self.posted=0
    def list_comments(self,*a): return [{"id": i+1, "body": b, "user": {"login":"bot"}} for i,b in enumerate(self.comments)]
    def post_comment(self,*a): self.posted+=1; self.comments.append(a[-1]); return {"id":1}
    def update_comment(self,*a): return {"id":1}

main.is_bot_author = lambda u: (u or {}).get("login") == "bot"
main.approve_if_clean = lambda *a, **k: False
main.already_approved = lambda *a, **k: False
main.unresolved_bot_thread_count = lambda *a, **k: -1
ctx = types.SimpleNamespace(config=types.SimpleNamespace(dry_run=False, language="zh"),
                            pr={"head":{"sha":"abc"}}, approved=False, inline_posted=False)
g = G(); main.act_on_clean_verdict(g, "o", "r", 80, ctx)
print("body:", " ".join(g.comments[0].split()) if g.comments else "(none)")
