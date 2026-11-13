"""One-off: one living status comment per gate, not one per repository."""

from pathlib import Path

root = Path(__file__).resolve().parent.parent
main_py = root / "review" / "main.py"
readme = root / "review" / "README.md"

text = main_py.read_text(encoding="utf-8")


def replace(old: str, new: str) -> None:
    global text
    assert text.count(old) == 1, (text.count(old), old[:70])
    text = text.replace(old, new)


replace(
    '''# An invisible marker that makes the build/test status one comment living on the pull
# request instead of one per run.
BUILD_STATUS_MARKER = "<!-- ai-review build status -->"
''',
    '''# An invisible marker that makes one gate's status one comment living on the pull
# request instead of one per run. It carries the label, because a repository can be a
# .NET solution and a UPM package at the same time — PeroSerde is both — and each gate
# posts its own result. With a single marker the second gate edited the first gate's
# comment out of existence: PeroSerde #9's Unity result, platform table and all,
# survived only in that comment's edit history, and the pull request showed ".NET:
# 编译通过" as if the package had never been tested.
BUILD_STATUS_MARKER = "<!-- ai-review build status"


def build_status_marker(label: str) -> str:
    """The marker that keeps one label's result in one comment."""
    return f"{BUILD_STATUS_MARKER}: {label} -->"
''',
)

replace(
    '''        log(f"{label}: no check run, so the result is posted as a comment instead.")
        post_status_comment(
            gh, owner, repo, number, summary + "\\n\\n" + BUILD_STATUS_MARKER,
            marker=BUILD_STATUS_MARKER,
        )''',
    '''        marker = build_status_marker(label)
        log(f"{label}: no check run, so the result is posted as a comment instead.")
        post_status_comment(
            gh, owner, repo, number, summary + "\\n\\n" + marker,
            marker=marker,
        )''',
)

replace('VERSION = "2026-10-29.unity.138"', 'VERSION = "2026-11-04.unity.139"')

main_py.write_text(text, encoding="utf-8", newline="\n")

readme_text = readme.read_text(encoding="utf-8")
old = (
    "And when the check run cannot be created, the summary is posted as a status "
    "comment instead — one living comment, carrying `<!-- ai-review build status -->` "
    "so a re-run edits it rather than stacking another green comment on every run. A "
    "comment by somebody else is never edited, marker or not."
)
new = (
    "And when the check run cannot be created, the summary is posted as a status "
    "comment instead — one living comment **per gate**, carrying "
    "`<!-- ai-review build status: Unity -->` or `...: .NET -->`, so a re-run edits it "
    "rather than stacking another green comment on every run. Per gate, because a "
    "repository can be a solution and a package at once: PeroSerde #9 ran both gates, "
    "and with one shared marker the .NET result edited the Unity comment out of "
    "existence — the platform table the Unity gate had just posted survived only in "
    "that comment's edit history, and the pull request read as if the package had never "
    "been tested. A comment by somebody else is never edited, marker or not."
)
assert readme_text.count(old) == 1
readme.write_text(
    readme_text.replace(old, new), encoding="utf-8", newline="\n"
)
print("patched")
