"""One-off: edits are matched like a human would, and a mismatch is retried once.

SQLite.net PR #1, second run: the model answered with edits, and edit 7's `find` text was
not in the file — one whitespace difference and the whole instruction is refused with
nothing to show for 70k tokens. A `find` that differs only in indentation or trailing
whitespace still names the lines it means; and if it really is absent, one more attempt
that says which edit failed is cheaper than giving up.
"""

from pathlib import Path

root = Path(__file__).resolve().parent.parent
main_py = root / "review" / "main.py"
text = main_py.read_text(encoding="utf-8")


def replace(old: str, new: str) -> None:
    global text
    assert text.count(old) == 1, (text.count(old), old[:80])
    text = text.replace(old, new)


# --------------------------------------------------------------------------- #
# Matching: exact first, then the same lines with whitespace ignored.
# --------------------------------------------------------------------------- #
replace(
    '''def _apply_edits(
    original: str, edits: Any
) -> "Tuple[Optional[str], str]":''',
    '''def _locate_ignoring_whitespace(
    text: str, needle: str
) -> Any:
    """Where ``needle`` is in ``text`` when only whitespace differs, or None.

    Returns ``(start, end)`` offsets, the string ``"ambiguous"`` when more than one
    window matches, or None. Models reproduce indentation badly — a tab for four
    spaces, a trailing space dropped — and a block that differs only in whitespace
    still names the lines it means.
    """
    need = [line.strip() for line in needle.split("\\n")]
    lines = text.split("\\n")
    if len(need) > len(lines):
        return None
    offsets: List[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line) + 1
    hits = [
        index
        for index in range(len(lines) - len(need) + 1)
        if [line.strip() for line in lines[index : index + len(need)]] == need
    ]
    if not hits:
        return None
    if len(hits) > 1:
        return "ambiguous"
    start = offsets[hits[0]]
    end = offsets[hits[0] + len(need) - 1] + len(lines[hits[0] + len(need) - 1])
    return start, end


def _apply_edits(
    original: str, edits: Any
) -> "Tuple[Optional[str], str]":''',
)

replace(
    '''    for index, edit in enumerate(edits, 1):
        if not isinstance(edit, dict):
            return None, f"edit {index} is not an object"
        find = str(edit.get("find") or "")
        replace_text = str(edit.get("replace") or "")
        if not find:
            return None, f"edit {index} has no `find` text"
        needle = find.replace("\\r\\n", "\\n")
        occurrences = normalised.count(needle)
        if occurrences == 0:
            return None, f"edit {index}: that text is not in the file"
        if occurrences > 1:
            return None, f"edit {index}: that text appears {occurrences} times"
        normalised = normalised.replace(needle, replace_text.replace("\\r\\n", "\\n"), 1)''',
    '''    for index, edit in enumerate(edits, 1):
        if not isinstance(edit, dict):
            return None, f"edit {index} is not an object"
        find = str(edit.get("find") or "")
        replacement = str(edit.get("replace") or "").replace("\\r\\n", "\\n")
        if not find:
            return None, f"edit {index} has no `find` text"
        needle = find.replace("\\r\\n", "\\n")
        occurrences = normalised.count(needle)
        if occurrences > 1:
            return None, f"edit {index}: that text appears {occurrences} times"
        if occurrences == 1:
            normalised = normalised.replace(needle, replacement, 1)
            continue
        # Not there verbatim. The same lines with the whitespace ignored are the same
        # instruction, and are what a model usually means when it mis-copies them.
        located = _locate_ignoring_whitespace(normalised, needle)
        if located == "ambiguous":
            return None, (
                f"edit {index}: that text appears more than once once whitespace is "
                "ignored"
            )
        if located is None:
            first = (needle.split("\\n") or [""])[0].strip()
            return None, (
                f"edit {index}: that text is not in the file (starts with {first[:70]!r})"
            )
        start, end = located
        normalised = normalised[:start] + replacement + normalised[end:]''',
)

# --------------------------------------------------------------------------- #
# One retry, and it says what went wrong.
# --------------------------------------------------------------------------- #
replace(
    '''def _code_change_messages(
    conversation: str, files_text: str, instruction: str, retry: bool = False
) -> List[Dict[str, str]]:
    """The request for a code change, worded for the first attempt or a retry."""
    if retry:''',
    '''def _code_change_messages(
    conversation: str,
    files_text: str,
    instruction: str,
    retry: bool = False,
    problem: str = "",
) -> List[Dict[str, str]]:
    """The request for a code change, worded for the first attempt or a retry."""
    if retry and problem:''',
)

replace(
    '''        tail = (
            "The previous answer did not arrive as valid JSON — it was cut off "
            "before the object ended, because it was as long as the files rather "
            "than as long as the change. Answer again with `find`/`replace` edits: "
            "never a complete file, not even for a small one. Fewer files, fewer "
            "lines, and the same JSON shape. Return ONLY the JSON."
        )''',
    '''        tail = (
            f"The previous answer could not be used: {problem}. Answer again with the "
            "same JSON shape. A `find` block is copied out of the file contents above "
            "character for character — indentation included — and must occur exactly "
            "once; two or three lines are usually enough to be unique. Return ONLY "
            "the JSON."
        )
    elif retry:''',
)

# --------------------------------------------------------------------------- #
# The handler: two attempts, and the second one knows what failed.
# --------------------------------------------------------------------------- #
start = text.index('    reply = ai.chat_message(\n        _code_change_messages(conversation, files_text, instruction), temperature=0.3')
end = text.index('    branch = f"ai-change-{int(datetime.now(timezone.utc).timestamp())}"')
new_block = '''    known = {fc["path"]: fc.get("content") or "" for fc in file_contents}
    changes: List[Dict[str, str]] = []
    commit_msg = ""
    cut = False
    problem = ""

    for attempt in (1, 2):
        reply = ai.chat_message(
            _code_change_messages(
                conversation, files_text, instruction,
                retry=attempt > 1, problem=problem,
            ),
            temperature=0.3,
        )
        result = (reply.get("content") or "").strip()
        # `length` is the model saying it ran out of output budget mid-answer, which
        # is what a JSON object stopping inside a string looks like from here.
        cut = (reply.get("finish_reason") or "") == "length"
        data: Optional[Dict[str, Any]] = None
        if result:
            try:
                parsed = _parse_json_response(result)
                data = parsed if isinstance(parsed, dict) else None
            except (ValueError, KeyError) as exc:
                log(
                    "Failed to parse code-change JSON"
                    + ("" if attempt == 1 else " on the second attempt")
                    + f": {exc}"
                )
        if data is None:
            problem = (
                "the answer was cut off before the JSON ended, because it was as long "
                "as the files rather than as long as the change"
                if cut
                else "the answer was not valid JSON"
            )
            if cut and attempt == 1:
                log("The answer was cut off before the JSON ended; asking again for edits only.")
            continue

        commit_msg = (data.get("message") or "ai: apply code changes").strip()
        changed_files = data.get("files") or []
        if not isinstance(changed_files, list) or not changed_files:
            problem = "the answer listed no file changes"
            continue

        # The change, applied to what this run already read. A file whose edit cannot
        # be placed stops the whole answer: a branch carrying half of the instruction
        # opens a pull request that looks finished and is not.
        applied: List[Dict[str, str]] = []
        for fc in changed_files:
            if not isinstance(fc, dict):
                continue
            path = fc.get("path")
            if not path:
                continue
            if fc.get("content") is not None:
                applied.append({"path": path, "content": str(fc.get("content"))})
                continue
            current = known.get(path)
            if current is None:
                problem = f"{path} is not on this branch"
                break
            updated, why = _apply_edits(current, fc.get("edits"))
            if updated is None:
                log(f"Cannot apply the edit to {path}: {why}")
                problem = f"{path}: {why}"
                break
            applied.append({"path": path, "content": updated})
        else:
            if applied:
                changes = applied
                problem = ""
            else:
                problem = "the answer changed no file"
            break
        if attempt == 2:
            break
        log(f"Answering again: {problem}")

    if problem or not changes:
        log(f"Code change failed: {problem or 'no change'}")
        gh.post_comment(
            owner, repo, number,
            _code_change_failure(author, cut, len(file_contents), omitted, problem),
        )
        return 0

'''
text = text[:start] + new_block + text[end:]

# The failure message says what the problem was, when there is one.
replace(
    '''def _code_change_failure(
    author: str, cut: bool, total: int, omitted: List[str]
) -> str:
    """What to tell the author when no usable change came back."""
    reason = (
        "模型的输出在生成到一半时被长度上限截断了"
        if cut
        else "模型返回的不是有效 JSON"
    )''',
    '''def _code_change_failure(
    author: str, cut: bool, total: int, omitted: List[str], problem: str = ""
) -> str:
    """What to tell the author when no usable change came back."""
    reason = (
        "模型的输出在生成到一半时被长度上限截断了"
        if cut
        else ("模型返回的改动无法应用" if problem else "模型返回的不是有效 JSON")
    )
    if problem and not cut:
        reason += f"（{problem}）"''',
)

main_py.write_text(text, encoding="utf-8", newline="\n")
print("patched")
