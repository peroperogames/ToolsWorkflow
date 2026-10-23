#!/bin/bash

# 从 tag 中提取版本号：规则写在 version_from_tag.sh 里，NuGet 那一步用的是同一份，
# 否则一次发布可能写出两个版本号。
source "$(dirname "${BASH_SOURCE[0]}")/version_from_tag.sh"
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
