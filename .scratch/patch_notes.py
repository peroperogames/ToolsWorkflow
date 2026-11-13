"""One-off: drop the unused `notes` field from the slice worker prompt."""

from pathlib import Path

path = Path(__file__).resolve().parent.parent / "review" / "main.py"
text = path.read_text(encoding="utf-8")

old = (
    '    "- `body` says what is wrong and the concrete fix.\\n"\n'
    '    "- `notes` is one sentence about something that involves files outside this slice, "\n'
    '    "or empty.\\n"\n'
)
new = '    "- `body` says what is wrong and the concrete fix.\\n"\n'

assert text.count(old) == 1, text.count(old)
path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
print("patched", path)
