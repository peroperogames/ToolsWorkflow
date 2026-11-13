from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\publish\resolve_channels.sh")
t = p.read_text(encoding="utf-8")
old = """# 这次发布用的是哪个 tag。只有无后缀的正式版本（`1.2.3`）会发到 PeroNPM 以外的
# 注册表：npmjs.org 与 nuget.org 上的版本号不可撤回，`1.2.3-base` 是同一个版本从
# base 分支出的另一次构建，`1.2.3-preview.1` 是预发布，两者都只发 PeroNPM。
TRIGGER_TAG="${GITHUB_REF_NAME:-${TAG:-${CI_COMMIT_TAG:-}}}"
source "$(dirname "${BASH_SOURCE[0]}")/version_from_tag.sh"
if [ -n "$TRIGGER_TAG" ]; then
    VERSION=$(extract_version "$TRIGGER_TAG") || exit 1
    if ! is_release_tag "$TRIGGER_TAG"; then
        if is_base_tag "$TRIGGER_TAG"; then
            echo "tag '$TRIGGER_TAG' is a base release ($VERSION): publishing to PeroNPM only, whatever else was asked for."
        else
            echo "tag '$TRIGGER_TAG' is a prerelease version ($VERSION): publishing to PeroNPM only, whatever else was asked for."
        fi
        CHANNELS="peronpm"
    fi
else
    echo "No release tag in the environment; publishing to the channels as asked."
fi
"""
new = """# 这次发布用的是哪个 tag。只有无后缀的正式版本（`1.2.3`）会发到 PeroNPM 以外的
# 注册表：npmjs.org 与 nuget.org 上的版本号不可撤回，`1.2.3-base` 是同一个版本从
# base 分支出的另一次构建，`1.2.3-preview.1` 是预发布，两者都只发 PeroNPM。规则本身
# 在 channels_for_tag.sh 里，那个脚本的另一个用途是让调用方知道"要不要准备 nuget 的
# 工程"。
here="$(dirname "${BASH_SOURCE[0]}")"
TRIGGER_TAG="${GITHUB_REF_NAME:-${TAG:-${CI_COMMIT_TAG:-}}}"
source "$here/version_from_tag.sh"
if [ -n "$TRIGGER_TAG" ]; then
    VERSION=$(extract_version "$TRIGGER_TAG") || exit 1
    if ! is_release_tag "$TRIGGER_TAG"; then
        if is_base_tag "$TRIGGER_TAG"; then
            echo "tag '$TRIGGER_TAG' is a base release ($VERSION): publishing to PeroNPM only, whatever else was asked for."
        else
            echo "tag '$TRIGGER_TAG' is a prerelease version ($VERSION): publishing to PeroNPM only, whatever else was asked for."
        fi
    fi
else
    echo "No release tag in the environment; publishing to the channels as asked."
fi
CHANNELS=$(bash "$here/channels_for_tag.sh" "$CHANNELS" "$TRIGGER_TAG") || exit 1
"""
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("resolver patched")
