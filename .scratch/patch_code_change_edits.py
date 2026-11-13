"""One-off: a code change is answered with edits, not whole files.

SQLite.net PR #1: the instruction implied rewriting large files, the model was asked for
complete file contents as JSON, hit the provider's 65,536-token output ceiling, and
answered with an unterminated string twice. An answer the size of the change instead of
the size of the files cannot be cut off by a big file.
"""

from pathlib import Path

root = Path(__file__).resolve().parent.parent
main_py = root / "review" / "main.py"
text = main_py.read_text(encoding="utf-8")


def replace(old: str, new: str) -> None:
    global text
    assert text.count(old) == 1, (text.count(old), old[:70])
    text = text.replace(old, new)


# --------------------------------------------------------------------------- #
# The request: edits, with whole-file content as the exception it is.
# --------------------------------------------------------------------------- #
replace(
    '''CODE_CHANGE_SYSTEM_PROMPT = (
    "You are a skilled software engineer. Given current file contents, "
    "conversation context, and the user's instruction, generate the required "
    "code changes.\\n\\n"
    "Return a JSON object:\\n"
    '{"message": "concise commit message", "files": [{"path": "relative/path", '
    '"content": "complete new file content"}]}\\n\\n'
    "Rules:\\n"
    "- Return the COMPLETE new file content for each file, not a diff.\\n"
    "- Only include files that actually change.\\n"
    "- Preserve the existing code style, conventions, and imports.\\n"
    "- Make minimal, focused changes that address the instruction.\\n"
    "- Return ONLY the JSON, no markdown fences, no extra text."
)''',
    '''CODE_CHANGE_SYSTEM_PROMPT = (
    "You are a skilled software engineer. Given current file contents, "
    "conversation context, and the user's instruction, generate the required "
    "code changes.\\n\\n"
    "Return a JSON object:\\n"
    '{"message": "concise commit message", "files": [{"path": "relative/path", '
    '"edits": [{"find": "<lines exactly as they are>", "replace": "<those lines '
    'as they should be>"}]}]}\\n\\n'
    "Rules:\\n"
    "- Change lines, not files. `find` is copied verbatim out of the file — enough "
    "lines that it occurs once — and `replace` is what those lines become. The "
    "answer is then the size of the change, not the size of the file, and a large "
    "file cannot exhaust the output limit.\\n"
    "- A whole-file `content` string is accepted only for a file that is new, or "
    "rewritten almost entirely; anything bigger than the change is cut off.\\n"
    "- Several edits to one file go in one `edits` array, in the order they apply.\\n"
    "- Only include files that actually change.\\n"
    "- Preserve the existing code style, conventions, and imports.\\n"
    "- Make minimal, focused changes that address the instruction.\\n"
    "- Return ONLY the JSON, no markdown fences, no extra text."
)''',
)

# --------------------------------------------------------------------------- #
# The retry says what to leave out, not just "smaller".
# --------------------------------------------------------------------------- #
replace(
    '''        tail = (
            "The previous answer did not arrive as valid JSON — it was cut off "
            "before the object ended. Answer again with a smaller object: only "
            "the files that must change, and only those changed lines' worth of "
            "content where the original allows it. Return ONLY the JSON."
        )''',
    '''        tail = (
            "The previous answer did not arrive as valid JSON — it was cut off "
            "before the object ended, because it was as long as the files rather "
            "than as long as the change. Answer again with `find`/`replace` edits: "
            "never a complete file, not even for a small one. Fewer files, fewer "
            "lines, and the same JSON shape. Return ONLY the JSON."
        )''',
)

# --------------------------------------------------------------------------- #
# Applying them: exact, unique, and never half a change.
# --------------------------------------------------------------------------- #
replace(
    '''def _code_change_messages(''',
    '''def _apply_edits(
    original: str, edits: Any
) -> "Tuple[Optional[str], str]":
    """``original`` with every find/replace applied, or None and the reason.

    Each `find` must occur exactly once, in the file as it is on the branch. That is
    the whole safety property of an edit: a block that occurs twice would be changed
    in whichever place came first, which is not a change anybody asked for.
    """
    if not isinstance(edits, list) or not edits:
        return None, "no edits"
    text = original
    # The model writes `\\n`; a file checked out on Windows has `\\r\\n`. Both are the
    # same change, so the comparison is made after normalising, and the file's own
    # line ending is restored at the end.
    crlf = "\\r\\n" in original
    normalised = text.replace("\\r\\n", "\\n")
    for index, edit in enumerate(edits, 1):
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
        normalised = normalised.replace(needle, replace_text.replace("\\r\\n", "\\n"), 1)
    return (normalised.replace("\\n", "\\r\\n") if crlf else normalised), ""


def _code_change_messages(''',
)

# --------------------------------------------------------------------------- #
# The failure message says what to do differently.
# --------------------------------------------------------------------------- #
replace(
    '''    return (
        f"@{author} 代码生成失败：{reason}（{detail}）。\\n\\n"
        "把指令缩小到具体文件会好很多，例如：`@perotoolsbot 把 "
        "Runtime/UIView.cs 里 RemoveSyncActiveGameObject 的 null 分支改成抛异常`。"
    )''',
    '''    return (
        f"@{author} 代码生成失败：{reason}（{detail}）。\\n\\n"
        "把指令缩小到具体文件和具体改动点会好很多，例如：`@perotoolsbot 把 "
        "Runtime/UIView.cs 里 RemoveSyncActiveGameObject 的 null 分支改成抛异常`。"
    )''',
)

# --------------------------------------------------------------------------- #
# The handler applies edits to what it already read.
# --------------------------------------------------------------------------- #
replace(
    '''    branch = f"ai-change-{int(datetime.now(timezone.utc).timestamp())}"
    try:
        log(f"Creating branch {branch} from {head_ref}...")
        gh.create_branch(owner, repo, branch, base_branch=head_ref)
        for fc in changed_files:
            path = fc.get("path")
            content = fc.get("content")
            if not path or content is None:
                continue
            gh.put_file(owner, repo, path, content, branch, commit_msg)''',
    '''    # The change, applied to what this run already read. A file whose edit cannot be
    # placed stops the whole thing: a branch carrying half of the instruction is a
    # pull request that looks finished and is not.
    known = {fc["path"]: fc.get("content") or "" for fc in file_contents}
    changes: List[Dict[str, str]] = []
    for fc in changed_files:
        if not isinstance(fc, dict):
            continue
        path = fc.get("path")
        if not path:
            continue
        if fc.get("content") is not None:
            changes.append({"path": path, "content": str(fc.get("content"))})
            continue
        current = known.get(path)
        if current is None:
            gh.post_comment(
                owner, repo, number,
                f"@{author} 代码生成失败：{path} 不在这条分支上，无法应用改动。",
            )
            return 0
        updated, why = _apply_edits(current, fc.get("edits"))
        if updated is None:
            log(f"Cannot apply the edit to {path}: {why}")
            gh.post_comment(
                owner, repo, number,
                f"@{author} 代码生成失败：{path} 的改动无法应用（{why}），没有提交 PR。",
            )
            return 0
        changes.append({"path": path, "content": updated})

    branch = f"ai-change-{int(datetime.now(timezone.utc).timestamp())}"
    try:
        log(f"Creating branch {branch} from {head_ref}...")
        gh.create_branch(owner, repo, branch, base_branch=head_ref)
        for change in changes:
            gh.put_file(owner, repo, change["path"], change["content"], branch, commit_msg)''',
)

replace(
    'VERSION = "2026-11-04.unity.145"', 'VERSION = "2026-11-04.unity.146"'
)

main_py.write_text(text, encoding="utf-8", newline="\n")
print("patched")
