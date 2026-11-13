import io
import sys

PATH = r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_code_change_edits.py"

with io.open(PATH, encoding="utf-8") as fh:
    source = fh.read()

anchor = 'print()\nif failures:'

addition = '''# 11. A file too large to send whole is shown as the lines the pull request changed,
#     numbered, and the rest of it is not sent. One such file was 60,890 prompt tokens.
huge = "\\n".join(f"// filler {i}" for i in range(1, 6001)) + "\\npublic void A() { }\\n"
patch = "@@ -6001,1 +6001,2 @@\\n public void A() { }\\n+    public void A() => Bar();"
text, omitted = main._code_change_context(
    [{"path": "SQLite.cs", "content": huge}],
    "改一下 SQLite.cs 的 A 方法",
    60000,
    {"SQLite.cs": patch},
)
if "```diff" in text and "6002: +" in text and "// filler 1" not in text and len(text) < 800:
    ok("a file too large to send whole is shown as its changed lines, numbered")
else:
    bad(f"text={text[:300]!r} omitted={omitted!r}")

# 12. A small file is still shown whole even when it was changed: the model needs the
#     code around the change, not only the change.
text, _ = main._code_change_context(
    [{"path": "Foo.cs", "content": SOURCE}], "改一下 Foo.cs 的 A 方法", 60000, {"Foo.cs": patch}
)
if "```diff" not in text and "public void B() { }" in text:
    ok("a small file is still sent whole")
else:
    bad(f"text={text[:300]!r}")

# 13. The budget counts what is sent, so one huge file no longer crowds out the others.
text, omitted = main._code_change_context(
    [{"path": "SQLite.cs", "content": huge}, {"path": "Test.cs", "content": SOURCE}],
    "改一下 SQLite.cs 的 A 方法",
    2000,
    {"SQLite.cs": patch},
)
if "Test.cs" in text and "public void B() { }" in text and not omitted:
    ok("a huge file costs its change, not its size, and the other files still fit")
else:
    bad(f"omitted={omitted!r} has_test={'Test.cs' in text}")

'''

if source.count(anchor) != 1:
    sys.exit("anchor not found once")
source = source.replace(anchor, addition + anchor)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(source)
print("patched")
