"""One-off: the review prompt says what counts as a finding, and what a duplicate is.

PeroSerde #11: 14 comments on 1,215 added lines, half of them preferences — missing
XML docs, no CancellationToken, ConfigureAwait(false), API symmetry, twenty-four
overloads worth refactoring, `file` types raising the minimum C# version — and the
whitespace defect was posted a second time fourteen minutes later, in English, on
another line.
"""

from pathlib import Path

root = Path(__file__).resolve().parent.parent
prompt = root / "review" / "prompt.md"
main_py = root / "review" / "main.py"

text = prompt.read_text(encoding="utf-8")


def replace(old: str, new: str) -> None:
    global text
    assert text.count(old) == 1, (text.count(old), old[:70])
    text = text.replace(old, new)


# 1. The bar: a finding is a defect with a victim, and a preference is not a finding.
replace(
    "## Using Conversation Context\n",
    """10. **A finding needs a victim: what breaks, for whom, and when.** Answer those three before you post, and let the comment say it. "An assembly compiled against 0.3.0 that still calls `GetWrittenBuffer()` throws `MissingMethodException` on its first call" is a finding; "the API would be more symmetric if it also had `Deserialize(Stream)`" is a preference, and a pull request is not improved by preferences — it is improved by not breaking. These are preferences unless you can name the victim:
    - an API that could be more symmetric, more convenient, or could take a `CancellationToken` — unless a caller in this repository needs it and cannot do without;
    - `ConfigureAwait(false)` on a library `await` — unless this repository calls the API from a single-threaded `SynchronizationContext`;
    - XML documentation on new members — one comment for the whole set, never one per member, and only where the file documents everything else by convention;
    - ten near-identical methods worth refactoring — unless the same fix has to be made in each and one will be missed;
    - a language feature that raises the minimum compiler version — only when the package's manifest, README or release notes claim support for an older one.
    **A defect that repeats is one finding.** Twenty-four overloads, two loops, three call sites: name every place in one comment, and do not post a second one for the next place you notice. The review that reads as nitpicking is the one that files every symptom separately.

## Using Conversation Context
""",
)

# 2. A duplicate is a duplicate in any language, on any line.
replace(
    "4. **Never state the same finding twice.** One finding, one comment.",
    """4. **Never state the same finding twice** — not in this run, not across runs, not in another language, not on another line. A finding an existing thread already covers is covered, however differently you would phrase it: when the same defect recurs elsewhere in the diff, that is the same comment, not a new one. Write in the review language only; a comment in another language cannot be compared with the ones before it and will be posted as new.""",
)

# 3. Workflow step 3 was the invitation to file preferences, one per line.
replace(
    "3. **Every finding goes on a line, including the ones that are not about a line.** Missing tests, a missing changelog or documentation entry, a design or process concern — anchor each to the closest changed line it relates to and post it there. Never drop a finding for lack of a line, and never stay silent because the PR is small. (This is about problems without a line — it is not licence to post praise; see guideline 3.)",
    "3. **Every finding goes on a line, including the ones that are not about a line.** Missing tests for code whose risk is concrete, a design or process concern that breaks something — anchor each to the closest changed line it relates to and post it there. Never drop a finding for lack of a line, and never stay silent because the PR is small. (This is about problems without a line — it is not licence to post praise, or a preference; see guidelines 3 and 10.)",
)

# 4. A resolved thread covers its defect everywhere, which is what the recurrence rule means.
replace(
    "- **Inline comments carry their thread state** — an entry reads `[inline <file>:<line>, thread resolved]` or `, thread open`. A resolved thread was already dealt with (fixed, or deliberately dismissed); treat it as addressed and do not re-flag the same issue. Only revisit it if the new changes make the problem reappear in a different form.",
    "- **Inline comments carry their thread state** — an entry reads `[inline <file>:<line>, thread resolved]` or `, thread open`. A resolved thread was already dealt with (fixed, or deliberately dismissed); treat it as addressed and do not re-flag the same issue anywhere in the diff. Only revisit it if the new changes make the problem reappear in a different form — a second instance of the same defect is not a different form.",
)

prompt.write_text(text, encoding="utf-8", newline="\n")

main_text = main_py.read_text(encoding="utf-8")
old_version = 'VERSION = "2026-11-04.unity.139"'
assert main_text.count(old_version) == 1
main_py.write_text(
    main_text.replace(old_version, 'VERSION = "2026-11-04.unity.140"'),
    encoding="utf-8",
    newline="\n",
)
print("patched")
