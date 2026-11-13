"""One-off: replace check 4 in check_worker_tools.py (edit tool hits Win32 1175)."""

import io
from pathlib import Path

path = Path(__file__).resolve().parent / "check_worker_tools.py"
text = path.read_text(encoding="utf-8")

start = text.index("# 4. ")
end = text.index("# 5. ")

new = '''# 4. And it cannot read past MAP_WORKER_READS: batched calls (several per step, the
# way a model asks for a few files at once) are what makes the read cap bind, since
# the step cap is smaller than the read cap.
gh = FakeGitHub()
batched = ScriptedClient(
    steps=[
        [call("read_file", path="srcs/Input/InputService.cs", offset=i * 2 + 1),
         call("read_file", path="srcs/Input/InputShortcut.cs", offset=i * 2 + 1)]
        for i in range(main.MAP_WORKER_STEPS)
    ],
)
main._worker_client = lambda ai: batched
try:
    main.review_file_groups(
        ai=None, pr=PR, files=FILES, all_files=FILES, threads="",
        max_tokens_per_slice=10_000, concurrency=1, deadline_seconds=60,
        gh=gh, owner="o", repo="r", heads="abc123",
    )
finally:
    main._worker_client = lambda ai: ScriptedClient([])
print(
    f"--- reads fetched: {len(gh.reads)} of {main.MAP_WORKER_STEPS * 2} asked in "
    f"{batched.chat_calls} step(s)"
)
if len(gh.reads) == main.MAP_WORKER_READS:
    ok(f"reads stop at {main.MAP_WORKER_READS} per slice")
else:
    bad(f"{len(gh.reads)} reads went through, expected {main.MAP_WORKER_READS}")

'''

path.write_text(text[:start] + new + text[end:], encoding="utf-8", newline="\n")
print("patched", path)
