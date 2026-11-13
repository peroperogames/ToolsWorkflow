import io
import sys

PATH = r"E:\Gatongone\GitClone\ToolsWorkflow\review\README.md"

with io.open(PATH, encoding="utf-8") as fh:
    source = fh.read()

old = """SQLite.net is the case that exposed it. Its default branch `main` held only `build.yml`, while `review.yml` sat on `peropero`, the branch its pull requests merge into. Every inline reply ran; `@perotoolsbot settle` on PR #1 produced no run and therefore no comment, and the settle never happened.
"""

new = """SQLite.net is the case that exposed it. Its default branch `main` held only `build.yml`, while `review.yml` sat on `peropero`, the branch its pull requests merge into. Every inline reply ran; `@perotoolsbot settle` on PR #1 produced no run and therefore no comment, and the settle never happened.

A fork is where this cannot be repaired by adding a file: its default branch mirrors upstream, and mirroring means anything committed there is upstream's to overwrite. Two routes remain.

- **Point the default branch at the branch that carries the caller** — a repository setting, not a commit, so the mirrored branch is untouched. New pull requests then open against that branch by default, which is the integration branch for a fork that way anyway.
- **Issue the command inside an inline review thread.** `pull_request_review_comment` runs from the pull request's own branches, so a reply to any of the bot's threads there is a command like any other. This needs no change to the repository at all, which is what makes it the route to use while the setting is still upstream's.
"""

if source.count(old) != 1:
    sys.exit("anchor not found once")
io.open(PATH, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
print("patched")
