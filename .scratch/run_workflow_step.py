#!/usr/bin/env python3
"""Print the `run:` script of one step of the reusable publish workflow.

The tests run the scripts exactly as they are written in the workflow, so they
cannot drift from what GitHub runs. Steps are looked up across every job, because
the publish is split over a self-hosted job and a GitHub-hosted one.
"""
import os
import sys

import yaml

WORKFLOW = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".github",
    "workflows",
    "publish-npm.yml",
)


def steps():
    with open(WORKFLOW, encoding="utf-8") as handle:
        doc = yaml.safe_load(handle)
    for job_name, job in doc["jobs"].items():
        for step in job["steps"]:
            yield job_name, step


def step_body(name):
    found = [(job, step) for job, step in steps() if step.get("name") == name]
    if not found:
        raise SystemExit("no step named %r" % name)
    if len(found) > 1:
        raise SystemExit("more than one step is named %r: %s" % (name, [job for job, _ in found]))
    job, step = found[0]
    if "run" not in step:
        raise SystemExit("the step %r has no run script" % name)
    return job, step["run"]


if __name__ == "__main__":
    if len(sys.argv) == 2:
        _, body = step_body(sys.argv[1])
        sys.stdout.write(body)
    elif len(sys.argv) == 3 and sys.argv[1] == "--job":
        # Which job a step belongs to, for the tests that care where it runs.
        job, _ = step_body(sys.argv[2])
        print(job)
    else:
        raise SystemExit("usage: run_workflow_step.py [--job] '<step name>'")
