"""One-off: a reply accepts a dismissal, and does not review.

PeroSerde #11: the author answered "ignore it." and got the finding restated as a new
English comment on the same line minutes later; "啰嗦" was answered with "但第二条不受
影响…" and then the thread was resolved a minute after that anyway.
"""

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
    '''    "repository's criteria) or `prompt(base): <what to change>` (the shared "
    "prompt), either of which opens a pull request for a human to merge."
)''',
    '''    "repository's criteria) or `prompt(base): <what to change>` (the shared "
    "prompt), either of which opens a pull request for a human to merge.\\n"
    "A reply is an answer, not a review: do not open findings in it. If something "
    "strikes you while answering, say it in the reply text — never as another inline "
    "comment over a point this pull request already has a thread for, and never as a "
    "second attempt at one the developer has just turned down.\\n"
    "When the developer dismisses a finding — \\"ignore it\\", \\"wrong\\", \\"by "
    "design\\", or simply that they are leaving the code as it is — that decision is "
    "theirs and is not a misunderstanding to correct. Acknowledge it in one sentence "
    "and, if they asked, close the thread. Do not argue the point again, do not "
    "restate it in other words, and do not re-raise it under a different heading: "
    "PeroSerde #11 is what the alternative looked like — \\"ignore it.\\" was answered "
    "with the same finding posted again in another language, and \\"啰嗦\\" was "
    "argued with before the thread was resolved a minute later anyway."
)''',
)

replace('VERSION = "2026-11-04.unity.140"', 'VERSION = "2026-11-04.unity.141"')

main_py.write_text(text, encoding="utf-8", newline="\n")

readme_text = readme.read_text(encoding="utf-8")
old = (
    "Comments on non-PR issues, bot comments, and comments that address neither the bot "
    "nor one of its threads are ignored. When the trigger came from an inline thread, "
    "the bot replies inside that same thread. If the model decides a comment needs no "
    "answer, it stays silent — nothing is posted, and the reason it gives is printed in "
    "the run log (`Ignored the comment: …`)."
)
new = old + """

**A reply is an answer, not a review.** It does not open findings: anything that strikes the model while answering goes into the reply text, never into another inline comment over a point the pull request already has a thread for.

**A dismissal is the author's decision.** When they answer a finding with "ignore it", "by design", "wrong", or simply that they are leaving the code as it is, that is the end of it: one sentence acknowledging the decision, and the thread is closed if they asked for that. The finding is not argued again, restated in other words, or re-raised under a different heading — PeroSerde #11 is what the alternative looked like: "ignore it." was answered with the same finding posted again in another language, and "啰嗦" with "但第二条不受影响…", a minute before the thread was resolved anyway."""
assert readme_text.count(old) == 1
readme.write_text(readme_text.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
