from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_resolve_step.sh")
t = p.read_text(encoding="utf-8")
# the duplicated base-tag block (a stray first run) goes; keep one clean case
old = '''out=$(cd /e/Gatongone/GitClone/CITest && env \\
  RUNNER_TEMP="$work" GITHUB_WORKSPACE=/e/Gatongone/GitClone/CITest \\
  GITHUB_ENV="$work/env-base.txt" GITHUB_OUTPUT="$work/out-base.txt" \\
  GITHUB_REPOSITORY=peroperogames/CITest GITHUB_REF_NAME=0.3.0-base \\
  HINT_DIR="" HINT_NUGET="" HINT_USER="Peropero" CHANNELS="peronpm,npmjs,nuget" \\
  NPM_URL="https://npm.example.com/" bash "$work/step.sh" 2>&1)
: > "$work/env-base.txt"
'''
assert t.count(old) == 1
t = t.replace(old, "")
p.write_text(t, encoding="utf-8", newline="\n")
print("cleaned")
