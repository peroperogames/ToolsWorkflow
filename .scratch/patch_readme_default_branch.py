import io
import sys

PATH = r"E:\Gatongone\GitClone\ToolsWorkflow\review\README.md"

with io.open(PATH, encoding="utf-8") as fh:
    source = fh.read()

anchor = """## Review pipeline
"""

addition = """### The caller has to be on the default branch

`issue_comment` is one of the events GitHub only runs from **the repository's default branch**. A comment on the pull request — `@perotoolsbot settle`, `@perotoolsbot review` — is an issue comment, so a repository whose caller exists only on a feature or release branch gets *no run at all*: not a failed one, not a skipped one, nothing in the Actions tab.

`pull_request` and `pull_request_review_comment` are not restricted that way, which is what makes the failure look arbitrary: replies inside an inline thread keep working, while a top-level comment on the same pull request silently does nothing. The repair is to have the caller on the default branch; other branches may keep their own copy.

SQLite.net is the case that exposed it. Its default branch `main` held only `build.yml`, while `review.yml` sat on `peropero`, the branch its pull requests merge into. Every inline reply ran; `@perotoolsbot settle` on PR #1 produced no run and therefore no comment, and the settle never happened.

## Review pipeline
"""

if source.count(anchor) != 1:
    sys.exit(f"anchor found {source.count(anchor)} times")
io.open(PATH, "w", encoding="utf-8", newline="\n").write(source.replace(anchor, addition, 1))
print("patched")
