"""Find where the version properties live in this fixture."""

from pathlib import Path

path = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\props-test\Core\PeroTools2.AccessKing.Core.csproj")
for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
    if "Version" in line:
        print(f"{index:3}: {line.strip()}")
