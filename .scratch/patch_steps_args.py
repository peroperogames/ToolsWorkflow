from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_publish_steps.sh")
t = p.read_text(encoding="utf-8")
old = '''if [ "$rc" = 0 ] && [ "$args" = "publish packages/com.prpr.accessking-0.4.0.tgz --registry https://registry.npmjs.org/" ]; then'''
new = '''# Absolute, and it has to be: `npm publish packages/x.tgz` is the GitHub shorthand
# owner/repo to npm, which turns into `git ls-remote ssh://git@github.com/packages/x.tgz.git`.
if [ "$rc" = 0 ] && [ "$args" = "publish $WORK/external/packages/com.prpr.accessking-0.4.0.tgz --registry https://registry.npmjs.org/" ]; then'''
assert t.count(old) == 1, t.count(old)
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
