import yaml, io
d = yaml.safe_load(io.open(r"E:\Gatongone\GitClone\ToolsWorkflow\.github\workflows\publish-npm.yml", encoding="utf-8"))
for job_name, job in d["jobs"].items():
    print("== job", job_name, "keys:", sorted(job.keys()))
for s in d["jobs"]["publish"]["steps"]:
    name = s.get("name")
    run = s.get("run")
    if "run" in s:
        print(f"step {name!r}: keys={sorted(s.keys())} run_len={len(run or '')}")
print("notify if:", repr(d["jobs"]["notify"]["if"])[:100])
