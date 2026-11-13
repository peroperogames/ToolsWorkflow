"""One-off: document the clean-verdict comment, and bump the version."""

from pathlib import Path

root = Path(__file__).resolve().parent.parent
main_py = root / "review" / "main.py"
readme = root / "review" / "README.md"

text = main_py.read_text(encoding="utf-8")
old = 'VERSION = "2026-10-29.unity.137"'
assert text.count(old) == 1
main_py.write_text(
    text.replace(old, 'VERSION = "2026-10-29.unity.138"'),
    encoding="utf-8",
    newline="\n",
)

text = readme.read_text(encoding="utf-8")


def replace(old: str, new: str) -> None:
    global text
    assert text.count(old) == 1, (text.count(old), old[:60])
    text = text.replace(old, new)


replace(
    "### There is no summary\n",
    """### A clean review that cannot approve says so

A review that finds nothing ends in an approval, and the approval is the report — unless it cannot be given. Unresolved threads of the bot's own withhold it, and RhythmAce-Neo #80 is what that left behind: 14 agent steps, 0 inline comments, `verdict=approve`, `approved=no`, and the pull request showed no sign that a review had run at all. A clean run had nowhere to put its result.

So a clean verdict that cannot approve posts one line — `本次审查没有发现新问题。还有 3 个审查线程未解决，所以没有批准。`, in the review's language — carrying `<!-- ai-review clean verdict -->` so a later run edits it instead of adding another. It names the count and no reasons: which threads are open is on the pull request already.

The comment is corrected rather than left behind. When a later run approves — this review resolving what was left, or the settle step doing it — the standing comment is rewritten to say so, and a pull request never keeps a sentence that has stopped being true. A first approval has no such comment to correct, and posts none; a clean verdict that did post inside comments leaves it alone, because the findings are the report then.

### There is no summary
""",
)

replace(
    "Praise is not a finding. A comment that only compliments a change — however technically detailed — is never posted; the approval is the only positive signal, so a clean PR stays silent.",
    "Praise is not a finding. A comment that only compliments a change — however technically detailed — is never posted; the approval is the only positive signal, so a clean pull request posts nothing. The one exception is a clean review that cannot approve at all: that one line above is the only way its result reaches the pull request.",
)

readme.write_text(text, encoding="utf-8", newline="\n")
print("patched")
