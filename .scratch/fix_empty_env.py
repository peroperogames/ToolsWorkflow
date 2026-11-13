import re
from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.github\workflows\publish-npm.yml")
lines = p.read_text(encoding="utf-8").split("\n")

# Remove any `env:` whose block is empty: the key alone is `env: null` to YAML and an
# "Unexpected value ''" to GitHub.
changed = True
while changed:
    changed = False
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^\s*env:\s*$", line):
            indent = len(line) - len(line.lstrip())
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            following = lines[j] if j < len(lines) else ""
            following_indent = len(following) - len(following.lstrip())
            if following.strip() and following_indent <= indent:
                changed = True
                i += 1
                continue
        out.append(line)
        i += 1
    lines = out
p.write_text("\n".join(lines), encoding="utf-8", newline="\n")
print("removed empty env blocks")
