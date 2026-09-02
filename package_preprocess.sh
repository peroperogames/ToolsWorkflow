#!/bin/bash

# 先处理 tag 后缀（base/variant），得到 CLEAN_TAG
tag_type=$(echo "$CI_COMMIT_TAG" | awk -F'-' '{print $NF}')
if [ "$tag_type" = "base" ]; then
    CLEAN_TAG=$(echo "$CI_COMMIT_TAG" | sed 's/-base$//')
elif [ "$tag_type" = "variant" ]; then
    CLEAN_TAG="$CI_COMMIT_TAG"
else
    echo "Tag suffix not 'base' or 'variant', exiting..."
    exit 1
fi

# 从 CLEAN_TAG 提取纯数字版本号
extract_version() {
    local tag="$1"
    tag="${tag#v}"
    tag="${tag#V}"
    if [[ $tag =~ ^([0-9]+\.[0-9]+\.[0-9]+) ]]; then
        echo "${BASH_REMATCH[1]}"
    else
        echo "$tag"   # 降级
    fi
}
CLEAN_VERSION=$(extract_version "$CLEAN_TAG")
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