"""One-off: add a get_file_diff check to check_worker_tools.py."""

from pathlib import Path

path = Path(__file__).resolve().parent / "check_worker_tools.py"
text = path.read_text(encoding="utf-8")

anchor = "print()\nif failures:"
assert text.count(anchor) == 1

new = '''# 6. get_file_diff is the worker's other hand: its own file, numbered, for free.
gh = FakeGitHub()
diff_client = ScriptedClient(
    steps=[[call("get_file_diff", path="srcs/Input/InputService.cs")],
           [call("get_file_diff", path="srcs/Secret/Other.cs")]],
    report={"findings": []},
)
main._worker_client = lambda ai: diff_client
try:
    main.review_file_groups(
        ai=None, pr=PR, files=FILES, all_files=FILES, threads="",
        max_tokens_per_slice=10_000, concurrency=1, deadline_seconds=30,
        gh=gh, owner="o", repo="r", heads="abc123",
    )
finally:
    main._worker_client = lambda ai: ScriptedClient([])
if gh.reads == []:
    ok("get_file_diff serves a file from the slice without spending a read")
else:
    bad(f"get_file_diff spent reads: {gh.reads}")


'''

path.write_text(text.replace(anchor, new + anchor), encoding="utf-8", newline="\n")
print("patched", path)
