"""Local check: a committed build artifact is not a finding, and reading one says so.

A mixed pull request — source plus the assembly its release ships — gets the same
"the DLL cannot be verified, confirm it was built from this source, a .pdb should not
be in version control" comment every time. It is not actionable, and the pipeline was
inviting it: the binary appeared in the diff as "_(no textual patch available)_", which
reads like something hidden rather than something that has no text.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main

failures = []


def ok(msg):
    print("ok   " + msg)


def bad(msg):
    print("FAIL " + msg)
    failures.append(msg)


# 1. The diff names what the file is.
pr = {"title": "t", "body": "", "user": {"login": "u"}, "base": {"sha": "b"}, "head": {"sha": "h"}}
files = [
    {"filename": "Generator/ReferenceSymbols.cs", "status": "modified", "additions": 3,
     "deletions": 1, "patch": "- a\n+ b"},
    {"filename": "Generator/Plugins/Serde.Generator.dll", "status": "modified",
     "additions": 0, "deletions": 0},
    {"filename": "Generator/Plugins/Serde.Generator.pdb", "status": "modified",
     "additions": 0, "deletions": 0},
]
text = main.build_diff_text(pr, files)
print("--- the binary lines in the diff:")
for line in text.splitlines():
    if line.startswith("_(") or "Plugins/Serde" in line:
        print("   ", line)
if "binary" in text and "no textual patch available" not in text:
    ok("a file without a text diff is named a binary or oversized file")
else:
    bad("the diff still says 'no textual patch available'")

# 2. Reading one says what it is, instead of surfacing a codec error.
class BinaryGitHub:
    def get_file_content(self, owner, repo, path, ref=None):
        raise UnicodeDecodeError("utf-8", b"\x00\x01", 0, 1, "invalid start byte")


ctx = main.ToolContext.__new__(main.ToolContext)
ctx.gh = BinaryGitHub()
ctx.owner, ctx.repo, ctx.heads = "o", "r", "h"
ctx.read_windows = set()
ctx.read_calls = 0
answer = main._tool_read_file({"path": "Plugins/Serde.Generator.dll"}, ctx)
print("--- read_file on a binary:")
print("   ", answer)
if "binary file" in answer and "no text to read" in answer and "codec" not in answer.lower():
    ok("reading a binary answers 'binary file', not a decode error")
else:
    bad(f"reading a binary answered: {answer}")

# 3. The rule is in the prompt the model is given.
prompt = (Path(__file__).resolve().parent.parent / "review" / "prompt.md").read_text(encoding="utf-8")
for needle in ("committed build artifact", "cannot be read as text", ".pdb"):
    if needle not in prompt:
        bad(f"the prompt does not mention {needle!r}")
if "committed build artifact" in prompt and "cannot be read as text" in prompt and ".pdb" in prompt:
    ok("the prompt carries the artifact rule")

# 4. And it stays a rule about artifacts, not a licence to ignore real problems.
if "concrete contradiction" not in prompt:
    bad("the prompt does not say when an artifact *is* worth a comment")
else:
    ok("the prompt still allows a comment when the diff contradicts the artifact")

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("OK")
