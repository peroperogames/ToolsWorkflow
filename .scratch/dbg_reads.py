import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(r"E:\Gatongone\GitClone\ToolsWorkflow") / "review"))
import main

FILES=[{"filename":"a.cs","status":"modified","additions":1,"deletions":0,"patch":"+x"}]
class G:
    def __init__(self): self.reads=[]
    def get_file_content(self,o,r,p,ref=None):
        self.reads.append(p); return "\n".join(f"l{i}" for i in range(1,301))

g=G()
t=main._SliceTools(g,"o","r","sha",FILES)
for i in range(8):
    print(i, repr(t.run("read_file", {"path":"a.cs"})[:60]))
print("fetches", len(g.reads), "read_calls", t.read_calls)
