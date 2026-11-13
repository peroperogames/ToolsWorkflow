"""One-off: document the bar for a finding, and guard the prompt with a check."""

from pathlib import Path

root = Path(__file__).resolve().parent.parent
readme = root / "review" / "README.md"

text = readme.read_text(encoding="utf-8")

old = "### There is no summary\n"
new = """### A finding needs a victim

A comment has to name what breaks, for whom, and when. PeroSerde #11 is why that sentence is in the prompt: 1,215 added lines and 14 comments, and half of them were preferences — no `CancellationToken` on the new async overloads, `ConfigureAwait(false)`, missing XML documentation, an API that would be more symmetric with a read side, twenty-four near-identical overloads worth refactoring, `file`-scoped types raising the minimum C# version. None of them names a caller that breaks. Together they are the review rewriting the pull request into the one it would have written itself, which is not what a review is for.

Guideline 10 says it as the shape of a preference: allowed only when you can name the victim — a downstream assembly that throws `MissingMethodException`, a platform that fails at runtime, a manifest that claims older support than the feature needs. Two related rules came out of the same pull request:

- **A defect that repeats is one finding.** Twenty-four overloads, two loops, three call sites: one comment naming every place, not one comment per place. The review that reads as nitpicking is the one that files every symptom separately.
- **A duplicate is a duplicate in any language, on any line.** The whitespace defect in #11 was posted twice on the same day, the second time in English on a different line, because the duplicate check compares text and two languages do not. Comments are written in the review language only, and a thread that already covers a defect covers it wherever the defect recurs.

### There is no summary
"""
assert text.count(old) == 1
readme.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
print("patched readme")
