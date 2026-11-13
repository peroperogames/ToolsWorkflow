import re
from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.github\workflows\publish-npm.yml")
t = p.read_text(encoding="utf-8")
pattern = re.compile(r"^\s*PACKAGE_DIR: \$\{\{ inputs\.working-directory \}\}\s*$")
lines = t.split("\n")
for i, line in enumerate(lines, 1):
    if "${{ inputs.working-directory }}" in line:
        print(i, repr(line))
