#!/bin/bash

# 处理tag
tag_type=`echo $CI_COMMIT_TAG | awk -F'-' '{print$NF}'`
if [ "$tag_type" = "base" ];then
    CI_COMMIT_TAG=`echo $CI_COMMIT_TAG | sed 's/-base$//'`
elif [ "$tag_type" = "variant" ];then
    CI_COMMIT_TAG=${CI_COMMIT_TAG}
else
    # echo "tag illegal.."
    exit
fi

# 获取包名
old_package_name=`grep "\"name\"\: " package.json | sed -n "1p" | awk -F'"' '{print $(NF-1)}'`
# 将包名和期望的前缀写入临时文件中
echo $old_package_name > old_package_name_file
echo $EXPECTED_PACKAGE_PREFIX > expected_package_prefix_file

# 获取包名的第一个部分（如com）
old_first=`awk -F'.' '{print $1}' old_package_name_file`
# 获取包名的第二个部分（如prpr）
old_second=`awk -F'.' '{print $2}' old_package_name_file`

# 获取期望包名的第一个部分（如com）
expected_first=`awk -F'.' '{print $1}' expected_package_prefix_file`
# 获取期望包名的第二个部分（如prpr）
expected_second=`awk -F'.' '{print $2}' expected_package_prefix_file`

# 如果包名的第一个部分相同，第二个部分不相同
if [ "$old_first" = "$expected_first" -a "$old_second" != "$expected_second" ]; then
    # 则获取第二个部分之后的部分，和期望的前缀进行拼接
    other=`cat old_package_name_file | cut  -d . -f 2-`
    new_package_name="$EXPECTED_PACKAGE_PREFIX.$other"
# 如果包名的第一个部分和第二个部分都不相同
elif [ "$old_first" != "$expected_first" ]; then
    # 则获取全部包名，直接将前缀加在前面
    other=`cat old_package_name_file`
    new_package_name="$EXPECTED_PACKAGE_PREFIX.$other"
# 如果包名的前两个部分都相同，那么新包名和旧包名就相同
else
    new_package_name=$old_package_name
fi

# 替换包名和版本号
sed -i "s/$old_package_name/$new_package_name/" package.json
sed -i "s/\"version\"\:*\"*.*.*\"/\"version\"\:\ \"$CI_COMMIT_TAG\"/" package.json

# 用于查看修改结果
cat package.json

# 删除临时文件
rm -f old_package_name_file
rm -f expected_package_prefix_file
