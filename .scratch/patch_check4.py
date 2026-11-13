"""One-off: give the fixture a hunk header so numbering is actually exercised."""

from pathlib import Path

path = Path(__file__).resolve().parent / "check_worker_tools.py"
text = path.read_text(encoding="utf-8")

old_patch = (
    '        "patch": "- old line\\n+public void Register(IHandler handler) { }\\n'
    '+public void Unregister() { }",'
)
new_patch = (
    '        "patch": "@@ -10,2 +10,5 @@\\n- old line\\n+public void Register(IHandler handler) { }\\n'
    '+public void Unregister() { }",'
)
assert text.count(old_patch) == 1
text = text.replace(old_patch, new_patch)

old_check = 'if "Register" in mine and mine is not theirs and theirs.startswith("error:"):'
new_check = (
    'numbered = re.search(r"^\\s*11: \\+public void Register", mine, re.M)\n'
    'if numbered and theirs.startswith("error:"):'
)
assert text.count(old_check) == 1
text = text.replace(old_check, new_check)

text = text.replace("import json\nimport sys", "import json\nimport re\nimport sys", 1)

path.write_text(text, encoding="utf-8", newline="\n")
print("patched", path)
