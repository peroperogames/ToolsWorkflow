import yaml, io
d = yaml.safe_load(io.open(r"E:\Gatongone\GitClone\ToolsWorkflow\.github\workflows\publish-npm.yml", encoding="utf-8"))
job = d["jobs"]["publish"]
print("defaults.run.working-directory =", job.get("defaults", {}).get("run", {}).get("working-directory"))
for s in job["steps"]:
    name = s.get("name") or s.get("uses")
    wd = s.get("working-directory")
    kind = "run" if "run" in s else "uses"
    env = s.get("env") or {}
    pkg = {k: v for k, v in env.items() if k in ("PACKAGE_DIR", "CI_PROJECT_DIR", "NUGET_PROJECT", "PLUGIN_PROJECT")}
    print(f"{kind:4} wd={str(wd):42} {name}  {pkg if pkg else ''}")
