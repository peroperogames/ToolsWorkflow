from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\review\README.md")
t = p.read_text(encoding="utf-8")
old = """Two bounds keep a worker from reading instead of reviewing. `MAP_WORKER_STEPS` (6) puts `Last step: call report_findings with what you have now.` in front of the last step, and `MAP_WORKER_READS` (8) caps the reads \u2014 which only binds when a model asks for several files in one step, since a dimension of the step budget is smaller than it. A worker that runs out of steps without reporting is not silent: `Map: a slice reviewer ran out of steps without reporting.` A read that asks for a window the worker already has still costs one of its reads, which is deliberate \u2014 a worker looping on one file should run out before the review behind it waits much longer.

The worker is not given the threads, and it does not describe what it could not judge: it reports findings, and nothing else it says is read. `notes` used to be asked for and thrown away."""
new = """Two bounds keep a worker from reading instead of reviewing. `MAP_WORKER_STEPS` (6) puts `Last step: call report_findings with what you have now.` in front of the last step, and `MAP_WORKER_READS` (8) caps the reads \u2014 which only binds when a model asks for several files in one step, because the step budget is smaller than the read budget. A worker that runs out of steps without reporting is not silent: `Map: a slice reviewer ran out of steps without reporting.` A read that asks for a window the worker already has still costs one of its reads, which is deliberate \u2014 a worker looping on one file should run out before the review behind it waits much longer.

What a worker says beyond its findings is not read, so the schema does not ask for anything beyond them: `notes` was in the prompt and dropped by the code, and it is gone."""
assert t.count(old) == 1, t.count(old)
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("fixed")
