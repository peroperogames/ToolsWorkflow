#!/bin/bash

set -e  # 遇到错误立即退出

# 处理 tag（如果 tag 以 -base 结尾则去掉，如果是 -variant 则保留原样）
tag_type=$(echo "$CI_COMMIT_TAG" | awk -F'-' '{print $NF}')
if [ "$tag_type" = "base" ]; then
    CI_COMMIT_TAG=$(echo "$CI_COMMIT_TAG" | sed 's/-base$//')
elif [ "$tag_type" = "variant" ]; then
    CI_COMMIT_TAG="$CI_COMMIT_TAG"
else
    echo "Error: Tag format is incorrect (must end with -base or -variant), current tag: $CI_COMMIT_TAG"
    exit 1
fi

# 获取当前包名
old_package_name=$(npm pkg get name | tr -d '"')
echo "Current package name: $old_package_name"


# 检查期望前缀是否已设置
if [ -z "$EXPECTED_PACKAGE_PREFIX" ]; then
    echo "Error: Environment variable EXPECTED_PACKAGE_PREFIX is not set"
    exit 1
fi

# 计算新包名（逻辑同之前）
old_first=$(echo "$old_package_name" | cut -d'.' -f1)
old_second=$(echo "$old_package_name" | cut -d'.' -f2)
expected_first=$(echo "$EXPECTED_PACKAGE_PREFIX" | cut -d'.' -f1)
expected_second=$(echo "$EXPECTED_PACKAGE_PREFIX" | cut -d'.' -f2)

if [ "$old_first" = "$expected_first" ] && [ "$old_second" != "$expected_second" ]; then
    other=$(echo "$old_package_name" | cut -d'.' -f2-)
    new_package_name="$EXPECTED_PACKAGE_PREFIX.$other"
elif [ "$old_first" != "$expected_first" ]; then
    new_package_name="$EXPECTED_PACKAGE_PREFIX.$old_package_name"
else
    new_package_name="$old_package_name"
fi

echo "New package name: $new_package_name"
echo "New version   : $CI_COMMIT_TAG"

# 使用 npm pkg 修改 name 和 version
npm pkg set name="$new_package_name"
npm pkg set version="$CI_COMMIT_TAG"

# 打印修改结果
echo "===== package.json ====="
cat package.json
echo "========================"