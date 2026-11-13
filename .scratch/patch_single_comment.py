from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_single_comment.py")
t = p.read_text(encoding="utf-8")
old = """    def create_check_run(self, *args, **kwargs):
        return None
"""
new = """    def create_check_run(self, *args, **kwargs):
        return None

    def list_comments(self, owner, repo, number):
        return []
"""
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
