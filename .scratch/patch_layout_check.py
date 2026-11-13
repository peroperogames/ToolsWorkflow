from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_version_commit_layout.sh")
t = p.read_text(encoding="utf-8")
old = '''run_in "$REPO/Unity" "$WORK/step-preprocess.sh" "$WORK/preprocess.log" \\
  CI_COMMIT_TAG=0.3.0-base EXPECTED_PACKAGE_PREFIX=com.prpr; rc=$?'''
new = '''run_in "$REPO/Unity" "$WORK/step-preprocess.sh" "$WORK/preprocess.log" \\
  CI_COMMIT_TAG=0.3.0-base EXPECTED_PACKAGE_PREFIX=com.prpr PACKAGE_ROOT="$REPO/Unity"; rc=$?'''
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
