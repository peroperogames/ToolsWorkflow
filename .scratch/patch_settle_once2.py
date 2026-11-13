import io
import sys

p = r"review/main.py"
s = io.open(p, encoding="utf-8").read()


def rep(old, new, count=1):
    global s
    if s.count(old) != count:
        sys.exit("anchor %d: %r" % (s.count(old), old[:70]))
    s = s.replace(old, new, count)


# 1. The outcome carries what was closed and why, so a settle can say it once.
rep('''    resolved: int = 0
    open: List[Dict[str, Any]] = field(default_factory=list)
    approved: bool = False
    unknown: bool = False''',
'''    resolved: int = 0
    open: List[Dict[str, Any]] = field(default_factory=list)
    # Threads this pass closed, with the decider's sentence: one list, so a settle
    # reports all of them in one place instead of one notification per thread.
    closed: List[Dict[str, Any]] = field(default_factory=list)
    approved: bool = False
    unknown: bool = False''')

# 2. The decider can be asked not to reply inside each thread.
rep('''    changed_paths: Optional["set[str]"] = None,
) -> SettleOutcome:
    """Judge the threads''',
'''    changed_paths: Optional["set[str]"] = None,
    reply: bool = True,
) -> SettleOutcome:
    """Judge the threads''')

rep('''        note = _resolution_note(wanted.get(tid, ""), language)
        _reply_in_thread(gh, owner, repo, number, c.get("comment_id"), note, c["path"])''',
'''        note = _resolution_note(wanted.get(tid, ""), language)
        outcome.closed.append(
            {"path": c.get("path"), "line": c.get("line"), "reason": note}
        )
        if reply:
            _reply_in_thread(
                gh, owner, repo, number, c.get("comment_id"), note, c["path"]
            )''')

# 3. The approving pass takes the same choice.
rep('''    changed_paths: Optional["set[str]"] = None,
) -> SettleOutcome:
    """Resolve the threads that are done with''',
'''    changed_paths: Optional["set[str]"] = None,
    reply: bool = True,
) -> SettleOutcome:
    """Resolve the threads that are done with''')

rep('''        diff_files=diff_files, conversation=conversation,
        skip_ids=skip_ids, language=language, changed_paths=changed_paths,
    )''',
'''        diff_files=diff_files, conversation=conversation,
        skip_ids=skip_ids, language=language, changed_paths=changed_paths,
        reply=reply,
    )''')

# 4. The settle command asks for one message.
rep('''        changed_paths=changed_paths,
        language=ctx.config.language,
    )''',
'''        changed_paths=changed_paths,
        language=ctx.config.language,
        reply=False,
    )''')

# 5. One message says the result and what it closed.
rep('''    if after < 0:
        return "读不到线程状态，详见 workflow 日志。"
    counts = f"未解决线程 {before} → {after}，" if before >= 0 else f"未解决线程 {after}，"
    if after == 0:
        if outcome.approved:
            return counts + "已 approve ✅"
        return counts + "approve 未提交（该提交此前已批准过，或没有权限）。"
    if outcome.unknown:
        return counts + "判定失败，详见 workflow 日志。"
    # Just the count: which thread stayed open is visible on the pull request, and
    # why is in the run log. Nothing is posted into a thread that stays open.
    return counts + "暂不 approve。"''',
'''    if after < 0:
        return "读不到线程状态，详见 workflow 日志。"
    counts = f"未解决线程 {before} → {after}，" if before >= 0 else f"未解决线程 {after}，"
    if after == 0:
        if outcome.approved:
            head = counts + "已 approve ✅"
        else:
            head = counts + "approve 未提交（该提交此前已批准过，或没有权限）。"
    elif outcome.unknown:
        head = counts + "判定失败，详见 workflow 日志。"
    else:
        # Which thread stayed open is visible on the pull request, and why it
        # stayed open is in the run log. Nothing is posted into that thread.
        head = counts + "暂不 approve。"
    return head + _closed_lines(outcome)


def _closed_lines(outcome: "SettleOutcome") -> str:
    """The threads this pass closed, and the sentence that closed each one.

    They used to be posted as a reply inside every thread — one notification
    each, so a settle that retired five threads arrived as five emails and a
    sixth saying how many were left. The same sentences fit in the one message
    the settle already posts.
    """
    if not outcome.closed:
        return ""
    shown = outcome.closed[:10]
    lines = ["", "", f"已关闭 {len(outcome.closed)} 条："]
    for item in shown:
        where = item.get("path") or "?"
        line = item.get("line")
        label = f"`{where}:{line}`" if line else f"`{where}`"
        reason = " ".join((item.get("reason") or "").split())
        lines.append(f"- {label} — {reason}" if reason else f"- {label}")
    if len(outcome.closed) > len(shown):
        lines.append(f"- …另有 {len(outcome.closed) - len(shown)} 条")
    return "\\n".join(lines)''')

io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("patched")
