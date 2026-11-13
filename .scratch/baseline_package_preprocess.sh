#!/bin/bash

# 从 tag 中提取版本号
# 从 CI_COMMIT_TAG 提取版本号，规则如下：
#   1) x.x.x-base       -> 提取纯数字版本 x.x.x
#   2) x.x.x-x-variant  -> 直接使用完整版本 x.x.x-x-variant
#   3) 其他格式          -> 报错并中断
extract_version() {
    local tag="$1"

    # 兼容可选的 v/V 前缀
    tag="${tag#v}"
    tag="${tag#V}"

    # 规则 1：x.x.x-base -> x.x.x
    if [[ $tag =~ ^([0-9]+\.[0-9]+\.[0-9]+)-base$ ]]; then
        echo "${BASH_REMATCH[1]}"
        return 0
    fi

    # 规则 2：x.x.x-x-variant -> 原样使用
    if [[ $tag =~ ^[0-9]+\.[0-9]+\.[0-9]+-.+-variant$ ]]; then
        echo "$tag"
        return 0
    fi

    # 规则 3：其他形式直接报错中断
    echo "Error: invalid version tag '$CI_COMMIT_TAG' (expected <version>-base or <version>-<x>-variant)" >&2
    return 1
}
CLEAN_VERSION=$(extract_version "$CI_COMMIT_TAG") || exit 1
echo "Extracted version: $CLEAN_VERSION"

# 包名处理
old_package_name=$(grep "\"name\"\: " package.json | sed -n "1p" | awk -F'"' '{print $(NF-1)}')
echo "$old_package_name" > old_package_name_file
echo "$EXPECTED_PACKAGE_PREFIX" > expected_package_prefix_file

old_first=$(awk -F'.' '{print $1}' old_package_name_file)
old_second=$(awk -F'.' '{print $2}' old_package_name_file)
expected_first=$(awk -F'.' '{print $1}' expected_package_prefix_file)
expected_second=$(awk -F'.' '{print $2}' expected_package_prefix_file)

if [ "$old_first" = "$expected_first" ] && [ "$old_second" != "$expected_second" ]; then
    other=$(cut -d . -f 2- old_package_name_file)
    new_package_name="$EXPECTED_PACKAGE_PREFIX.$other"
elif [ "$old_first" != "$expected_first" ]; then
    other=$(cat old_package_name_file)
    new_package_name="$EXPECTED_PACKAGE_PREFIX.$other"
else
    new_package_name="$old_package_name"
fi

escaped_old=$(echo "$old_package_name" | sed 's/\./\\./g')
escaped_new=$(echo "$new_package_name" | sed 's/\./\\./g')
sed -i "s/$escaped_old/$escaped_new/" package.json

# 替换版本号
sed -i "s/\(\"version\"\s*:\s*\)\"[^\"]*\"/\1\"$CLEAN_VERSION\"/" package.json

cat package.json
rm -f old_package_name_file expected_package_prefix_file
