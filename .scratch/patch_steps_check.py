from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_publish_steps.sh")
t = p.read_text(encoding="utf-8")
pairs = [
    ('if [ "$rc" = 0 ] && [ -f "$WORK/fixture/publish-artifacts/com.prpr.accessking-0.4.0.tgz" ]; then',
     'if [ "$rc" = 0 ] && [ -f "$RUNNER_TEMP/publish-artifacts/com.prpr.accessking-0.4.0.tgz" ]; then'),
    ('if ls "$WORK/fixture/publish-artifacts/" | grep -q \'\\.nupkg$\'; then',
     'if ls "$RUNNER_TEMP/publish-artifacts/" | grep -q \'\\.nupkg$\'; then'),
]
for old, new in pairs:
    assert t.count(old) == 1, (old, t.count(old))
    t = t.replace(old, new)
p.write_text(t, encoding="utf-8", newline="\n")
print("patched")
