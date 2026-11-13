from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_resolve_step.sh")
t = p.read_text(encoding="utf-8")
old = '''python_bin=$(command -v python3 || command -v python)
"$python_bin" - "$WORKFLOW" "$work/step.sh" <<'PY'
import sys, yaml, io
path, out = sys.argv[1], sys.argv[2]
workflow = yaml.safe_load(io.open(path, encoding="utf-8"))
steps = workflow["jobs"]["publish"]["steps"]
step = [s for s in steps if s.get("name") == "Resolve the package directory and the NuGet project"][0]
io.open(out, "w", encoding="utf-8", newline="\\n").write(step["run"] + "\\n")
PY
'''
new = '''# The step's script, lifted out by indentation: what runs is the file's own text, not a
# copy that could drift from it.
awk '
  /- name: Resolve the package directory and the NuGet project/ { found = 1 }
  found && /^        run: \\|$/ { capture = 1; next }
  capture && /^          / { sub(/^          /, ""); print; next }
  capture { exit }
' "$WORKFLOW" > "$work/step.sh"
if [ ! -s "$work/step.sh" ]; then
  echo "FAIL could not lift the resolve step out of $WORKFLOW"
  exit 1
fi
'''
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
