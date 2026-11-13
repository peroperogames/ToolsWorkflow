"""One-off: make check 6 assert the refusal and the numbering, not just reads."""

from pathlib import Path

path = Path(__file__).resolve().parent / "check_worker_tools.py"
text = path.read_text(encoding="utf-8")

start = text.index("# 6. ")
end = text.index("print()\nif failures:")

new = '''# 6. get_file_diff is the worker's other hand: its own file, numbered, for free.
gh = FakeGitHub()
tools = main._SliceTools(gh, "o", "r", "abc123", FILES)
mine = tools.run("get_file_diff", {"path": "srcs/Input/InputService.cs"})
theirs = tools.run("get_file_diff", {"path": "srcs/Secret/Other.cs"})
print(f"--- diff head: {mine.splitlines()[0][:70]!r}")
if "Register" in mine and mine is not theirs and theirs.startswith("error:"):
    ok("get_file_diff serves the slice's own file and refuses another, free of reads")
else:
    bad(f"get_file_diff: mine={mine[:80]!r}, theirs={theirs[:80]!r}")
if gh.reads == []:
    ok("get_file_diff spends no read")
else:
    bad(f"get_file_diff spent reads: {gh.reads}")


'''

path.write_text(text[:start] + new + text[end:], encoding="utf-8", newline="\n")
print("patched", path)
