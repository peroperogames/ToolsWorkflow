from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_publish_steps.sh")
t = p.read_text(encoding="utf-8")
old = '''run_step() { # script, workdir, log, env assignments...
  local script="$1" dir="$2" log="$3"; shift 3
  ( cd "$dir" && env "$@" bash -e "$script" ) > "$log" 2>&1
}'''
new = '''run_step() { # script, workdir, log, env assignments...
  local script="$1" dir="$2" log="$3"; shift 3
  # PACKAGE_ROOT and PACKAGE_DIR are what the resolve step writes to $GITHUB_ENV; a step
  # that moves into the package reads the first of them.
  ( cd "$dir" && env PACKAGE_ROOT="$dir" PACKAGE_DIR="." "$@" bash -e "$script" ) > "$log" 2>&1
}'''
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
