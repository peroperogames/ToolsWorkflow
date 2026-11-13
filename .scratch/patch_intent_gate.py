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


# 1. The classifier explains the difference between an order and deliberation.
old_prompt = '''INTENT_CLASSIFIER_PROMPT = (
    "Classify the intent of this GitHub comment directed at you (a code review bot).\\n"
    "Reply with EXACTLY one of these four words, nothing else:\\n"
    "- 'review' — the user wants you to review this PR now.\\n"
    "- 'inline_comment' — the user asks you to leave an inline / line-level "
    "comment on the code, e.g. 'inline comment 一下', '留个行内评论'.\\n"
    "- 'code_change' — the user wants the SOURCE CODE of the repo under review "
    "changed (fix a bug, add a feature, refactor).\\n"
    "- 'reply' — anything else: questions, acknowledgements, discussion, or a "
    "request to review differently ('be shorter', 'be stricter'). Changing how "
    "you review is NOT a classified intent — it only happens through an explicit "
    "`prompt(this):` / `prompt(base):` command, which never reaches this "
    "classifier.\\n"
    "Rules:\\n"
    "- Only choose 'code_change' when the repo's actual source code must change.\\n"
    "- If a comment contains an acknowledgement or quoted reply and no clear "
    "request, choose 'reply'."
)'''

new_prompt = '''INTENT_CLASSIFIER_PROMPT = (
    "Classify what this GitHub comment asks of you, a code review bot.\\n"
    "Reply with EXACTLY one of these four words, nothing else:\\n"
    "- 'review' — the author wants this pull request reviewed now.\\n"
    "- 'inline_comment' — the author asks for an inline, line-level comment, "
    "e.g. 'inline comment 一下', '留个行内评论'.\\n"
    "- 'code_change' — the author orders you to change the repository's source "
    "code now: what to change and how it should end up are both there, and "
    "nothing in the comment argues against making the change.\\n"
    "- 'reply' — everything else: questions, acknowledgements, discussion, a "
    "design remark, a warning about a change, or asking to review differently. "
    "Changing how you review is not a classified intent — that only happens "
    "through an explicit `prompt(this):` / `prompt(base):` command, which never "
    "reaches this classifier.\\n"
    "Rules:\\n"
    "- An imperative is not an order when the same comment argues against it, "
    "or explains that the current behaviour is a deliberate decision: '把吞错去掉…"
    "但这正是有意引入的软失败设计，属于库级契约变更' is the author weighing a "
    "change, not asking for it. Choose 'reply'.\\n"
    "- Describing what the code does today, or what a change would break, is "
    "discussion ('reply'). Asking you to make the change is 'code_change'.\\n"
    "- A requirement attached to a request ('改吧，但保持向后兼容') still asks "
    "for the change: 'code_change'.\\n"
    "- If the comment is an acknowledgement, or quotes a reply and asks for "
    "nothing, choose 'reply'."
)'''
replace(old_prompt, new_prompt)

# 2. A change is looked at twice before anything is generated.
replace(
    '''IMPROVE_PROMPT_SYSTEM_PROMPT = (''',
    '''CHANGE_ORDER_PROMPT = (
    "Decide one thing about this GitHub comment: does its author order a change "
    "to the repository's source code, or is the author discussing one?\\n"
    "Answer with EXACTLY one word, 'order' or 'discussion'.\\n"
    "- 'order': the author asks for the source to be changed and expects that to "
    "happen now.\\n"
    "- 'discussion': the author is weighing the change — noting that it is a "
    "breaking or library-level contract change, citing who introduced the current "
    "behaviour and why, arguing for or against it — even when the wording is "
    "imperative.\\n"
    "The comment is a reply; the thread it answers is given with it."
)


IMPROVE_PROMPT_SYSTEM_PROMPT = (''',
)

# 3. The classifier takes the thread, and a change is confirmed before it is made.
old_classify = '''def classify_intent(ai: AIClient, body: str) -> str:
    """Classify what a comment is asking the bot to do — review, comment, code, reply.

    Deliberately never yields a prompt change: that intent is reserved for the
    explicit `prompt(this):` / `prompt(base):` command, which is parsed
    deterministically before this classifier runs.
    """
    try:
        result = ai.chat(
            [
                {"role": "system", "content": INTENT_CLASSIFIER_PROMPT},
                {"role": "user", "content": body},
            ],
            temperature=0.0,
        )
        intent = pick_intent(result)
        log(f"Classified intent: {intent}")
        return intent
    except Exception as exc:  # noqa: BLE001 - fall back to a normal reply
        log(f"Warning: intent classification failed ({exc}); defaulting to reply.")
        return "reply"
'''

new_classify = '''def _with_thread(body: str, context: str) -> str:
    """The comment, and the thread it replies to when there is one."""
    if not context:
        return body
    return f"## The thread this replies to\\n\\n{context}\\n\\n## The comment\\n\\n{body}"


def is_change_order(ai: AIClient, body: str, context: str = "") -> bool:
    """Whether the author asks for a change to be made, or is weighing one.

    One comment can read both ways: "把吞错整体去掉…但这正是有意引入的软失败
    设计，属于库级契约变更" was read as an order, and the pull request it produced
    did the thing the sentence warned against. A change writes to the repository
    and is public, so the one decision that cannot be taken back is asked twice,
    with the thread the comment answers.
    """
    try:
        result = ai.chat(
            [
                {"role": "system", "content": CHANGE_ORDER_PROMPT},
                {"role": "user", "content": _with_thread(body, context)},
            ],
            temperature=0.0,
        )
    except Exception as exc:  # noqa: BLE001 - the first answer already said change
        log(f"Warning: could not double-check the request ({exc}); treating it as one.")
        return True
    text = (result or "").strip().lower()
    if "discussion" in text:
        log("That reads as discussion of a change, not a request for one.")
        return False
    if "order" not in text:
        log(f"The second look said {text[:40]!r}; treating it as a request.")
    return True


def classify_intent(ai: AIClient, body: str, context: str = "") -> str:
    """Classify what a comment is asking the bot to do — review, comment, code, reply.

    Deliberately never yields a prompt change: that intent is reserved for the
    explicit `prompt(this):` / `prompt(base):` command, which is parsed
    deterministically before this classifier runs.
    """
    try:
        result = ai.chat(
            [
                {"role": "system", "content": INTENT_CLASSIFIER_PROMPT},
                {"role": "user", "content": _with_thread(body, context)},
            ],
            temperature=0.0,
        )
        intent = pick_intent(result)
        if intent == "code_change" and not is_change_order(ai, body, context):
            intent = "reply"
        log(f"Classified intent: {intent}")
        return intent
    except Exception as exc:  # noqa: BLE001 - fall back to a normal reply
        log(f"Warning: intent classification failed ({exc}); defaulting to reply.")
        return "reply"
'''
replace(old_classify, new_classify)

# 4. The dispatch hands it the parent comment of the thread.
replace(
    "        intent = classify_intent(ai, body)\n",
    "        intent = classify_intent(ai, body, thread_context)\n",
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(source)
print("patched")
