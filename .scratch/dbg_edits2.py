import sys, types
from pathlib import Path
sys.path.insert(0, r"E:\Gatongone\GitClone\ToolsWorkflow\review")
import main

# whitespace-insensitive match
src = "public class Foo\n{\n    public void A() { }\n}\n"
upd, why = main._apply_edits(src, [{"find": "\tpublic void A() { }", "replace": "    public void A() => Bar();"}])
print("tabs:", why or "applied", "|", "Bar" in (upd or ""))

upd, why = main._apply_edits(src, [{"find": "    public void A() { }   ", "replace": "    public void A() => Bar();"}])
print("trailing spaces:", why or "applied", "|", "Bar" in (upd or ""))

# ambiguous once whitespace is ignored
dup = "class A\n{\n  void X() { }\n  void X() { }\n}\n"
upd, why = main._apply_edits(dup, [{"find": "void X() { }", "replace": "void Y() { }"}])
print("ambiguous:", why or "applied")

# genuinely absent
upd, why = main._apply_edits(src, [{"find": "void Nope()", "replace": "x"}])
print("absent:", why)
