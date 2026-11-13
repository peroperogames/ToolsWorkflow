from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_status_without_check_run.py")
t = p.read_text(encoding="utf-8")

old4 = '''earlier = {"id": 7, "body": "old summary\\n\\n" + main.BUILD_STATUS_MARKER,
           "user": {"login": "perotoolsbot[bot]"}}'''
new4 = '''earlier = {"id": 7, "body": "old summary\\n\\n" + main.build_status_marker("Unity"),
           "user": {"login": "perotoolsbot[bot]"}}'''
assert t.count(old4) == 1
t = t.replace(old4, new4)

old5 = '''foreign = {"id": 8, "body": "mine\\n\\n" + main.BUILD_STATUS_MARKER, "user": {"login": "tanyyt"}}'''
new5 = '''foreign = {"id": 8, "body": "mine\\n\\n" + main.build_status_marker("Unity"), "user": {"login": "tanyyt"}}'''
assert t.count(old5) == 1
t = t.replace(old5, new5)

old_body = 'if "EditMode" in body and main.BUILD_STATUS_MARKER in body:'
new_body = 'if "EditMode" in body and main.build_status_marker("Unity") in body:'
assert t.count(old_body) == 1
t = t.replace(old_body, new_body)

p.write_text(t, encoding="utf-8", newline="\n")
print("patched")
