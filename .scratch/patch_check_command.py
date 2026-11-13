import io
import sys

PATH = r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_review_shape.py"
source = io.open(PATH, encoding="utf-8").read()

anchor = "print()\nif failures:"
addition = '''# 9. The command path builds the same review as a push does. It was the one path
#    left out: `@perotoolsbot review` posted an empty body and lost the analysis's
#    findings, because only the push path handed them over.
command_call = source[
    source.index("def handle_review_request("):
    source.index("def settle_after_review(")
]
if (
    "review_body=review_body," in command_call
    and "carried_comments=_read_static_comments(owner, repo, number, pr)" in command_call
    and "review_body = gates.extra_context" in command_call
):
    ok("a review asked for by command carries the result and the held findings")
else:
    bad("the command path still posts an empty review body")

'''

if source.count(anchor) != 1:
    sys.exit("anchor not found once")
io.open(PATH, "w", encoding="utf-8", newline="\n").write(
    source.replace(anchor, addition + anchor)
)
print("patched")
