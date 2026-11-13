import io
import sys

PATH = r"E:\Gatongone\GitClone\ToolsWorkflow\review\main.py"

with io.open(PATH, encoding="utf-8") as fh:
    source = fh.read()


def replace(old, new, count=1):
    global source
    if source.count(old) != count:
        sys.exit(f"anchor found {source.count(old)} times: {old[:70]!r}")
    source = source.replace(old, new, count)


# 1. The block accepts being shown whole regardless of size.
replace(
    '''def _code_change_block(fc: Dict[str, str], patch: str) -> str:''',
    '''def _code_change_block(fc: Dict[str, str], patch: str, whole: bool = False) -> str:''',
)
replace(
    '''    if patch and estimate_tokens(content) > LARGE_FILE_TOKENS:''',
    '''    if patch and not whole and estimate_tokens(content) > LARGE_FILE_TOKENS:''',
)

# 2. The context builder takes the files to send whole anyway.
replace(
    '''    patches: Optional[Dict[str, str]] = None,
) -> Tuple[str, List[str]]:''',
    '''    patches: Optional[Dict[str, str]] = None,
    whole_files: Optional[List[str]] = None,
) -> Tuple[str, List[str]]:''',
)
replace(
    '''    ``patches`` is what the pull request changed per file, used only for the files
    too large to send whole. The edit is still applied to the file as read — this
    decides what is read, not what is written.
    """
    patches = patches or {}''',
    '''    ``patches`` is what the pull request changed per file, used only for the files
    too large to send whole; ``whole_files`` names files to send in full anyway,
    which is what a retry does for the file an answer could not place an edit in.
    The edit is still applied to the file as read — this decides what is read, not
    what is written.
    """
    patches = patches or {}
    whole = set(whole_files or [])''',
)
replace(
    '''        block = _code_change_block(fc, patches.get(path, ""))''',
    '''        block = _code_change_block(fc, patches.get(path, ""), path in whole)''',
)

# 3. A retry after an edit that could not be placed sends that file in full.
replace(
    '''    known = {fc["path"]: fc.get("content") or "" for fc in file_contents}
    changes: List[Dict[str, str]] = []
    commit_msg = ""
    cut = False
    problem = ""
''',
    '''    known = {fc["path"]: fc.get("content") or "" for fc in file_contents}
    changes: List[Dict[str, str]] = []
    commit_msg = ""
    cut = False
    problem = ""
    whole_files: List[str] = []
''',
)
replace(
    '''        if attempt == 2:
            break
        log(f"Answering again: {problem}")''',
    '''        if attempt == 2:
            break
        # The edit was quoted out of a change, and it is not there: the lines it
        # means are somewhere else in the file, so the retry reads all of it.
        failed_path = problem.split(":", 1)[0].strip()
        if failed_path in known and failed_path not in whole_files:
            whole_files.append(failed_path)
            files_text, omitted = _code_change_context(
                file_contents, instruction, max_tokens_per_chunk, patches, whole_files
            )
            log(f"Showing {failed_path} in full for the retry.")
        log(f"Answering again: {problem}")''',
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(source)
print("patched")
