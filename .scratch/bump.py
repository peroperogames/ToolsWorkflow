import io
import sys

path = r"E:\Gatongone\GitClone\ToolsWorkflow\review\main.py"
target = sys.argv[1] if len(sys.argv) > 1 else "2026-11-04.unity.148"
source = io.open(path, encoding="utf-8").read()
lines = source.splitlines(True)
for index, line in enumerate(lines):
    if line.startswith("VERSION = "):
        print("was", line.strip())
        lines[index] = 'VERSION = "%s"\n' % target
        break
else:
    raise SystemExit("no VERSION line")
io.open(path, "w", encoding="utf-8", newline="\n").write("".join(lines))
print("now", 'VERSION = "%s"' % target)
