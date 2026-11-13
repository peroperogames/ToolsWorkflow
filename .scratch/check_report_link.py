"""Local check: every comment that reports a build carries the reports' URL."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main

RUN = "39586837484"
PAGE = f"https://github.com/peroperogames/UIQueen/actions/runs/{RUN}#artifacts"
ARTIFACT = (
    f"https://github.com/peroperogames/UIQueen/actions/runs/{RUN}/artifacts/12407029397"
)
GATES = "**构建与测试**\n\n⚠️ Unity: 编译通过；PlayMode 测试运行失败（Unity 退出码 6），没有产出报告。"

for name in ("REVIEW_ARTIFACT_URL",):
    os.environ.pop(name, None)
os.environ["GITHUB_REPOSITORY"] = "peroperogames/UIQueen"
os.environ["GITHUB_RUN_ID"] = RUN

# The rebuild comment, before the upload has happened (a manual run, or a caller
# that does not use the upload step): the run's artifact page.
os.environ.pop("REVIEW_ARTIFACT_URL", None)
body = main.rebuild_comment_body("Unity package com.prpr.uiqueen", GATES, 2)
print("--- rebuild comment, no artifact URL in the environment")
print(body)
assert PAGE in body, body
assert body.rstrip().endswith(PAGE), body

# The same comment written by the review step after the upload: the artifact's own
# download URL, which is what a reader wants to click.
os.environ["REVIEW_ARTIFACT_URL"] = ARTIFACT
body = main.rebuild_comment_body("Unity package com.prpr.uiqueen", GATES, 0)
print("--- rebuild comment, after the upload")
print(body)
assert ARTIFACT in body and PAGE not in body, body
assert "Unity 退出码 6" in body, "the gates' own words must survive"

# Nothing to link at all: no URL, no line — not an empty link.
os.environ.pop("REVIEW_ARTIFACT_URL", None)
os.environ.pop("GITHUB_RUN_ID", None)
assert main.report_link_line() == "", main.report_link_line()
body = main.rebuild_comment_body("Unity package com.prpr.uiqueen", "", 0)
assert "完整报告" not in body, body
print("--- without a run id there is no reports line")
print("OK")
