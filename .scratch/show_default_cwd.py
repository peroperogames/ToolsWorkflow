import yaml, io
d = yaml.safe_load(io.open(r"E:\Gatongone\GitClone\ToolsWorkflow\.github\workflows\publish-npm.yml", encoding="utf-8"))
for s in d["jobs"]["publish"]["steps"]:
    if "run" not in s or s.get("working-directory"):
        continue
    print("=" * 70)
    print(s.get("name"))
    print("-" * 70)
    print(s["run"][:600])
