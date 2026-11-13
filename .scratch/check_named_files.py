"""Local check: a thread's named files are resolved against the pull request."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main

BODY = (
    "[低] `.idea/` 等 IDE 缓存已清理，但三个 Eclipse/Buildship 本地文件仍在本 PR 中："
    "`AndroidProject~/.project`、`nativeaudio/.project`、`nativeaudio/.classpath`。"
    "建议把这些也一并从 PR 移除（现在 `AndroidProject~/.gitignore` 中忽略了 "
    "`.project` / `.classpath`）"
)

print("named:", main.named_files(BODY))
assert main.named_files(BODY) == [".idea", ".project", ".classpath", ".gitignore"], main.named_files(BODY)

CHANGED = {
    "AndroidProject~/.gitignore",
    "AndroidProject~/nativeaudio/.gitignore",
    "AndroidProject~/nativeaudio/build.gradle",
}
lines = main._named_files_lines(BODY, CHANGED)
print(lines)
assert "named file `.project`: not among the files this pull request changes" in lines, lines
assert "named file `.classpath`: not among the files this pull request changes" in lines, lines
assert "named file `.gitignore`: changed by this pull request (AndroidProject~/.gitignore" in lines, lines

# No file list: nothing is claimed.
assert main._named_files_lines(BODY, None) == ""

# A body without backticked file names says nothing.
assert main._named_files_lines("就看一眼吧", CHANGED) == ""
print("OK")
