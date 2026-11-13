import yaml

d = yaml.safe_load(open(r"E:\Gatongone\GitClone\ToolsWorkflow\.github\workflows\publish-npm.yml", encoding="utf-8"))
c = d[True]["workflow_call"]
print("inputs:", ", ".join(c["inputs"]))
print("secrets:")
for name, spec in c["secrets"].items():
    print(f"  {name}: required={spec.get('required')}")
for name, job in d["jobs"].items():
    print(
        f"job {name}: runner={job.get('runs-on')} needs={job.get('needs')} "
        f"perms={job.get('permissions')} steps={len(job['steps'])} outputs={job.get('outputs')}"
    )
