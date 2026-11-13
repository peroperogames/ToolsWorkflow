import io
import sys

PATH = r"E:\Gatongone\GitClone\ToolsWorkflow\review\main.py"

with io.open(PATH, encoding="utf-8") as fh:
    source = fh.read()


def replace(old, new, count=1):
    global source
    if source.count(old) != count:
        sys.exit(f"anchor found {source.count(old)} times, expected {count}: {old[:60]!r}")
    source = source.replace(old, new, count)


# 1. The system prompt gains the rule about a file shown as its changed lines.
replace(
    '    "- Return ONLY the JSON, no markdown fences, no extra text."\n',
    '    "- A long file arrives as the lines the pull request changed, each numbered "\n'
    '    "with its line in the file: quote `find` from those lines.\\n"\n'
    '    "- Return ONLY the JSON, no markdown fences, no extra text."\n',
)

# 2. The context builder renders a large file as its change, and counts what it shows.
old_context = '''def _code_change_context(
    file_contents: List[Dict[str, str]],
    instruction: str,
    max_tokens_per_chunk: int,
) -> Tuple[str, List[str]]:
    """The files to show the model, and the ones that did not fit.

    A code change is asked for by name — "fix the N+1 in `src/foo.py`" — and the
    pull request can carry forty files, including a test file with three
    thousand lines. Sending all of it spends the context on code the instruction
    never mentions, and it makes a cut-off answer *more* likely, not less: the
    model has to reply with complete file contents, so a bigger input buys a
    bigger output. Files the instruction names come first, then the rest in the
    order they arrived, until the budget is spent.
    """
    budget = max_tokens_per_chunk
'''

new_context = '''LARGE_FILE_TOKENS = 8_000


def _code_change_block(fc: Dict[str, str], patch: str) -> str:
    """One file as the model should read it: all of it, or just the change.

    A vendored file of six thousand lines is where an instruction goes to die: it
    costs more than the whole review to send, and the lines the model needs are
    the ones the pull request changed. Those lines are shown with their numbers in
    the file, so a `find` copied out of them is a `find` that matches.
    """
    path = fc.get("path") or "?"
    content = fc.get("content") or ""
    if patch and estimate_tokens(content) > LARGE_FILE_TOKENS:
        return (
            f"The pull request changed the lines below in {path}. The file is too "
            "long to send whole, so they are all that is shown; each line carries "
            f"its number in the file.\\n```diff\\n{annotate_diff(patch)}\\n```"
        )
    return f"```\\n{content}\\n```"


def _code_change_context(
    file_contents: List[Dict[str, str]],
    instruction: str,
    max_tokens_per_chunk: int,
    patches: Optional[Dict[str, str]] = None,
) -> Tuple[str, List[str]]:
    """The files to show the model, and the ones that did not fit.

    A code change is asked for by name — "fix the N+1 in `src/foo.py`" — and the
    pull request can carry forty files, including a test file with three
    thousand lines. Sending all of it spends the context on code the instruction
    never mentions, and it makes a cut-off answer *more* likely, not less: the
    model has to reply with complete file contents, so a bigger input buys a
    bigger output. Files the instruction names come first, then the rest in the
    order they arrived, until the budget is spent.

    ``patches`` is what the pull request changed per file, used only for the files
    too large to send whole. The edit is still applied to the file as read — this
    decides what is read, not what is written.
    """
    patches = patches or {}
    budget = max_tokens_per_chunk
'''

replace(old_context, new_context)

# 3. The selection loop measures what it will actually show.
replace(
    '''    chosen: List[Dict[str, str]] = []
    omitted: List[str] = []
    used = 0
    for fc in named + rest:
        size = estimate_tokens(fc.get("content") or "") + estimate_tokens(fc.get("path") or "") + 8
        if chosen and used + size > budget:
            omitted.append(fc.get("path") or "?")
            continue
        chosen.append(fc)
        used += size

    text = "\\n\\n".join(
        f"### {fc['path']}\\n```\\n{fc.get('content') or ''}\\n```" for fc in chosen
    )
    return text, omitted
''',
    '''    chosen: List[str] = []
    omitted: List[str] = []
    used = 0
    for fc in named + rest:
        path = fc.get("path") or "?"
        block = _code_change_block(fc, patches.get(path, ""))
        size = estimate_tokens(block) + estimate_tokens(path) + 8
        if chosen and used + size > budget:
            omitted.append(path)
            continue
        chosen.append(f"### {path}\\n{block}")
        used += size

    return "\\n\\n".join(chosen), omitted
''',
)

# 4. The caller hands the patches over.
replace(
    '''    log("Generating code changes...")
    files_text, omitted = _code_change_context(
        file_contents, instruction, max_tokens_per_chunk
    )
''',
    '''    patches = {
        f.get("filename") or "": f.get("patch") or ""
        for f in files
        if f.get("patch")
    }
    log("Generating code changes...")
    files_text, omitted = _code_change_context(
        file_contents, instruction, max_tokens_per_chunk, patches
    )
''',
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(source)
print("patched")
