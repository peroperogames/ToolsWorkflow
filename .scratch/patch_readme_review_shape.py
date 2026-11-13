import io
import sys

PATH = r"E:\Gatongone\GitClone\ToolsWorkflow\review\README.md"
source = io.open(PATH, encoding="utf-8").read()


def rep(old, new, count=1):
    global source
    if source.count(old) != count:
        sys.exit(f"anchor found {source.count(old)} times: {old[:70]!r}")
    source = source.replace(old, new, count)


# The static analysis no longer posts on its own when a review will follow it.
rep(
    "post each `WARNING`/`ERROR` on a changed line as its own inline comment prefixed `ReSharper:`",
    "collect each `WARNING`/`ERROR` on a changed line, prefixed `ReSharper:`, for "
    "the review step to post — the findings arrive in the same review as the model's, "
    "rather than first as comments of their own; a run with no review step (a "
    "`rebuild`) posts them as one review at the end of the analysis",
)

# The settle result is a review body.
rep(
    "Each thread it closes gets its reason posted *inside* that thread — a reply, not a thread — and one comment reports the outcome, including the case where everything is resolved but the approval was not submitted because this commit was already approved:",
    "Each thread it closes gets its reason posted *inside* that thread — a reply, not a thread — and the outcome is posted as the body of a review, which is what a verdict about the pull request is; when it approved, the approval itself carries it and nothing else is posted:",
)

io.open(PATH, "w", encoding="utf-8", newline="\n").write(source)
print("patched")
