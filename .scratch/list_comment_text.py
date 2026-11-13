"""List the Chinese literals that end up in pull request comments."""

import re
from pathlib import Path

CJK = re.compile(r"[\u4e00-\u9fff]")
INTERESTING = ("post_comment", "status_lines.append", "lines.append", "return f\"", "return \"")

for path in ("review/main.py", "review/unity_runner.py", "review/dotnet_runner.py"):
    print(f"===== {path}")
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not CJK.search(stripped) or stripped.startswith(("#", "//")):
            continue
        if any(marker in stripped for marker in INTERESTING):
            print(f"{number:5}: {stripped[:160]}")
