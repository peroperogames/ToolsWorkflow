"""Local check: the comment's run-page link becomes the artifact's own URL."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import main

RUN = "39586837484"
PAGE = f"https://github.com/peroperogames/UIQueen/actions/runs/{RUN}#artifacts"
ARTIFACT = (
    f"https://github.com/peroperogames/UIQueen/actions/runs/{RUN}/artifacts/1234567890"
)
OTHER_PAGE = "https://github.com/peroperogames/UIQueen/actions/runs/11111111#artifacts"


class FakeGitHub:
    def __init__(self, comments):
        self.comments = comments
        self.updates = []

    def list_comments(self, owner, repo, number):
        return self.comments

    def update_comment(self, owner, repo, comment_id, body):
        self.updates.append((comment_id, body))
        return {"id": comment_id}


def body_with_link(page=PAGE):
    return (
        "🔧 **重新构建与测试**（只跑门禁，未做评审）\n"
        "⚠️ Unity: 编译通过；PlayMode 测试运行失败（Unity 退出码 6），没有产出报告。\n"
        f"\n完整报告（XML 与日志）：{page}"
    )


os.environ["GITHUB_REPOSITORY"] = "peroperogames/UIQueen"
os.environ["GITHUB_RUN_ID"] = RUN
os.environ["REVIEW_ARTIFACT_URL"] = ARTIFACT

gh = FakeGitHub(
    [
        {"id": 501, "body": body_with_link()},
        {"id": 502, "body": body_with_link(OTHER_PAGE)},
        {"id": 503, "body": "一条没有链接的普通评论"},
    ]
)
assert main.stage_artifact_link(gh, "peroperogames", "UIQueen", 3) == 0
assert [comment for comment, _ in gh.updates] == [501], gh.updates
edited = gh.updates[0][1]
assert ARTIFACT in edited and PAGE not in edited, edited
assert "重新构建与测试" in edited and "PlayMode 测试运行失败" in edited, edited
assert OTHER_PAGE in gh.comments[1]["body"], "an older run's comment must not move"
print("the comment of this run points at the artifact, the older one does not move")

# Already edited: running the stage twice must not rewrite anything.
gh2 = FakeGitHub([{"id": 601, "body": body_with_link(ARTIFACT)}])
main.stage_artifact_link(gh2, "peroperogames", "UIQueen", 3)
assert gh2.updates == [], gh2.updates
print("a second run of the stage edits nothing")

# No artifact URL: nothing uploaded, nothing to say.
del os.environ["REVIEW_ARTIFACT_URL"]
gh3 = FakeGitHub([{"id": 701, "body": body_with_link()}])
main.stage_artifact_link(gh3, "peroperogames", "UIQueen", 3)
assert gh3.updates == [], gh3.updates
assert gh3.comments[0]["body"] == body_with_link(), "the link must stay usable"
print("no upload leaves the run-page link in place")
print("OK")
