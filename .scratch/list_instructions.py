"""Chinese literals that read as instructions ('请…', '详见…') in posted text."""

import re
from pathlib import Path

for path in ("review/main.py", "review/unity_runner.py", "review/dotnet_runner.py"):
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not re.search(r"[\u4e00-\u9fff]", stripped):
            continue
        if stripped.startswith(("#", "//")):
            continue
        if "请" in stripped or "详见" in stripped:
            print(f"{path}:{number}: {stripped[:150]}")
