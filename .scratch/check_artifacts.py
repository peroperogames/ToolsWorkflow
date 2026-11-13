"""Local check: the reports land where the upload step looks for them.

Builds a fake per-PR state directory shaped like the runner's, runs the real
`share_artifacts`, and checks what arrives in the checkout — including that the
directory name is one `upload-artifact` will actually walk.
"""

import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "review"))

root = Path(tempfile.mkdtemp(prefix="artifacts-check-"))
state = root / "state"
workspace = root / "workspace"
workspace.mkdir()

meta = state / "peroperogames" / "UIQueen-PR3" / ".ai-review"
meta.mkdir(parents=True)
for name in (
    "tests-EditMode.xml",
    "tests-PlayMode.xml",
    "tests-PlayMode.log",
    "tests-PlayMode.editor.log",
    "resharper-1.xml",
    "editor.log",
    "checks-39586837484_2.json",
    "session.jsonl",
    ".lock",
):
    (meta / name).write_text("x", encoding="utf-8")
(meta / "pkg").mkdir()
(meta / "pkg" / "package.json").write_text("{}", encoding="utf-8")

os.environ["REVIEW_WORK_DIR"] = str(state)
os.environ["GITHUB_WORKSPACE"] = str(workspace)

import main  # noqa: E402 - needs the environment above

main._CURRENT_PR = ("peroperogames", "UIQueen", 3)
main.share_artifacts()

target = workspace / main.ARTIFACTS_DIRNAME
got = sorted(p.name for p in target.iterdir()) if target.is_dir() else []
print(f"ARTIFACTS_DIRNAME = {main.ARTIFACTS_DIRNAME!r}")
print(f"copied into {target}:")
for name in got:
    print(f"  {name}")

expected = sorted(
    {
        "tests-EditMode.xml",
        "tests-PlayMode.xml",
        "tests-PlayMode.log",
        "tests-PlayMode.editor.log",
        "resharper-1.xml",
        "editor.log",
        "checks-39586837484_2.json",
    }
)
assert got == expected, f"copied {got}\nexpected {expected}"
assert not main.ARTIFACTS_DIRNAME.startswith("."), "a hidden directory is skipped by upload-artifact"

action = (HERE / "review" / "action.yml").read_text(encoding="utf-8")
path_line = re.search(r"path: \$\{\{ github\.workspace \}\}/(\S+)", action)
assert path_line, "no upload path in action.yml"
assert path_line.group(1) == main.ARTIFACTS_DIRNAME + "/", path_line.group(1)
print(f"action.yml upload path agrees: {path_line.group(0)}")

# Nothing resolved means nothing to copy, and no directory left behind to upload.
empty = Path(tempfile.mkdtemp(prefix="artifacts-empty-"))
os.environ["GITHUB_WORKSPACE"] = str(empty)
main._CURRENT_PR = ("", "", 0)
main.share_artifacts()
assert list(empty.iterdir()) == [], "copy before a pull request is known must write nothing"
print("no pull request resolved: nothing written")
print("OK")
