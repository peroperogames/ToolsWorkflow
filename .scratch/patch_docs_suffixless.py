"""One-off: the documentation and the version note still describe the `-base` rule."""

from pathlib import Path

root = Path(__file__).resolve().parent.parent
workflow = root / ".github" / "workflows" / "publish-npm.yml"
readme = root / "publish" / "README.md"
update_readme = root / "publish" / "update_readme_version.sh"


def replace(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, (text.count(old), old[:70])
    return text.replace(old, new)


text = workflow.read_text(encoding="utf-8")
text = replace(
    text,
    "  # Only after every channel that ran came out green, and only for a `-base` tag:",
    "  # Only after every channel that ran came out green, and only for a release tag:",
)
text = replace(
    text,
    """          # `0.3.0-base` are not the same string.""",
    """          # `0.3.0+002` are not the same string.""",
)
workflow.write_text(text, encoding="utf-8", newline="\n")

readme_text = readme.read_text(encoding="utf-8")
readme_text = replace(
    readme_text,
    """| `0.3.0-base` | `0.3.0` |
| `v0.3.0-base` | `0.3.0` |""",
    """| `0.3.0` | `0.3.0` |
| `v0.3.0` | `0.3.0` |""",
)
readme_text = replace(
    readme_text,
    "   itself, because `0.3.0` and `0.3.0-base` are not the same string to a consumer.",
    "   itself, because `0.3.0` and `v0.3.0` are not the same string to a consumer.",
)
readme_text = replace(
    readme_text,
    "| Send Feishu notification (`notify`) | Only for a `-base` tag, and only when every channel that ran came out green. |",
    "| Send Feishu notification (`notify`) | Only for a release tag — a version with no suffix — and only when every channel that ran came out green. |",
)
readme_text = replace(
    readme_text,
    "| `FEISHU_WEBHOOK`, `FEISHU_SECRET` | yes | The notification for `-base` releases. |",
    "| `FEISHU_WEBHOOK`, `FEISHU_SECRET` | yes | The notification for releases (a version with no suffix). |",
)
readme.write_text(readme_text, encoding="utf-8", newline="\n")

update_text = update_readme.read_text(encoding="utf-8")
update_text = replace(
    update_text,
    "#   PACKAGE_NAME=com.prpr.accessking NEW_VERSION=0.3.0 GIT_REF=0.3.0-base \\",
    "#   PACKAGE_NAME=com.prpr.accessking NEW_VERSION=0.3.0 GIT_REF=0.3.0 \\",
)
update_text = replace(
    update_text,
    "# to npm and tags its releases `0.3.0-base`, so a git URL pointing at `0.3.0` would",
    "# to npm and tags its releases with the version itself, so a git URL pointing at",
)
update_readme.write_text(update_text, encoding="utf-8", newline="\n")
print("patched")
