"""Local check: a comment that weighs a change is not an order to make it.

SQLite.net PR #1: a reply in the bot's own thread said what removing the swallow
would mean — "这属于库级契约变更" — and the bot read it as an instruction, opened
PR #2, and made exactly the change the sentence was warning about. These are the
properties that keep that from happening again without requiring a magic command.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main

failures = []


def ok(msg):
    print("ok   " + msg)


def bad(msg):
    print("FAIL " + msg)
    failures.append(msg)


class AI:
    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    def chat(self, messages, temperature=0.0, **kwargs):
        self.prompts.append(messages)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


COMMENT = (
    "把 ExecuteNonQuery 的吞错整体去掉，让 Insert/Update/Delete/InsertAll/Execute "
    "也全部抛异常，而不是返回 -1。但这正是 f107415 \"feat: IOError callback\" "
    "有意引入的软失败设计，这属于库级契约变更"
)
THREAD = "perotoolsbot[bot] (Runtime/sqlite-net/SQLite.cs:1271):\n\n守卫只加在五处…"

# 1. Weighing a change is a reply, not a code change — the exact comment that
#    produced PR #2.
ai = AI(["code_change", "discussion"])
intent = main.classify_intent(ai, COMMENT, THREAD)
if intent == "reply":
    ok("a comment that weighs a change is a reply, not a code change")
else:
    bad(f"the comment that opened PR #2 still classifies as {intent!r}")

# 2. Both questions read the thread the comment answers, not only the sentence.
if (
    len(ai.prompts) == 2
    and THREAD.splitlines()[0] in ai.prompts[0][-1]["content"]
    and THREAD.splitlines()[0] in ai.prompts[1][-1]["content"]
    and COMMENT in ai.prompts[1][-1]["content"]
):
    ok("the parent comment is given to both questions")
else:
    bad("the thread context did not reach the classifier and the second look")

# 3. A real order still changes code, and costs the second look.
ai = AI(["code_change", "order"])
intent = main.classify_intent(ai, "@perotoolsbot 把 Runtime/Foo.cs 的 Bar 改成抛异常", THREAD)
if intent == "code_change" and len(ai.prompts) == 2:
    ok("a stated request still becomes a code change")
else:
    bad(f"intent={intent!r} calls={len(ai.prompts)}")

# 4. Anything that is not a change is classified once; no second look is paid.
ai = AI(["review"])
intent = main.classify_intent(ai, "@perotoolsbot 重新 review 一下", "")
if intent == "review" and len(ai.prompts) == 1:
    ok("a review request is classified once")
else:
    bad(f"intent={intent!r} calls={len(ai.prompts)}")

# 5. A second look that cannot be made does not silently drop an honest request:
#    the first answer said change, so the change goes ahead.
ai = AI(["code_change", RuntimeError("network down")])
intent = main.classify_intent(ai, "@perotoolsbot 把 Foo.cs 的 A 改成 B", "")
if intent == "code_change":
    ok("a failed second look keeps the change the first answer found")
else:
    bad(f"intent={intent!r}")

# 6. The rubric carries the distinction, so the prompt is not only words about
#    "the source code must change".
rubric = main.INTENT_CLASSIFIER_PROMPT
if "weighing a change" in rubric and "deliberate decision" in rubric:
    ok("the classifier says how an imperative that argues against itself reads")
else:
    bad("the classifier rubric lost the order-versus-discussion rule")

# 7. The dispatch really passes the thread it replies to.
source = (Path(__file__).resolve().parent.parent / "review" / "main.py").read_text(encoding="utf-8")
if "classify_intent(ai, body, thread_context)" in source:
    ok("the dispatch hands the classifier the parent comment")
else:
    bad("the dispatch does not pass the thread context")

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("OK")
