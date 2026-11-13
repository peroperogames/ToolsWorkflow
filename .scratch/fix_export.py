from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.github\workflows\publish-npm.yml")
t = p.read_text(encoding="utf-8")
old = """          NUGET_USER="$HINT_USER" bash "$tools/resolve_channels.sh\""""
new = """          # Exported, or the resolver — a child process — sees an empty project and
          # refuses the nuget channel it was just told about.
          export NUGET_PROJECT
          NUGET_USER="$HINT_USER" bash "$tools/resolve_channels.sh\""""
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
