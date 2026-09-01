#!/bin/bash

#set -e 
#set -x
echo "####原有目录：####"
find $CI_PROJECT_DIR -maxdepth 1 -type d -printf "%f\n"
echo "###################"
#获取项目根目录名称；
declare -a arr
declare -a brr
# 使用find获取子目录,存入arr数组
#arr=($(find $CI_PROJECT_DIR -maxdepth 1 -type d -printf "%f\n"))
# 使用find获取子目录,存入arr数组
mapfile -t arr < <(find "$CI_PROJECT_DIR" -maxdepth 1 -type d -printf "%f\n")

#检索packages.json文件，找到目标文件目录名；
mapfile -t brr < <(grep "~" $CI_PROJECT_DIR/package.json | cut -d'~' -f1 | cut -d ':' -f2 | sed 's/.//' | sed 's/.//')
#brr=($(grep "~" $CI_PROJECT_DIR/package.json | cut -d'~' -f1 | cut -d ':' -f2 | sed 's/.//' | sed 's/.//'))
echo "${brr[@]}"
#去重
declare -A uniq_brr

for i in "${brr[@]}"; do
   uniq_brr["$i"]=1 
done

brr=()

for i in "${!uniq_brr[@]}"; do
   brr+=("$i")
done
echo "packages.json里检测出的目录有: ${brr[@]}"
#根据目标目录名更改根目录对应的目录名，添加~；
same=false
for i in "${arr[@]}"; do
   echo "开始对目录 $i 进行判断"
   for j in "${brr[@]}"; do
      if [ "${i}" == "${j}" ]; then
        echo "正在处理: $i"
        mv "$CI_PROJECT_DIR/${i}" "$CI_PROJECT_DIR/${i}~"
        ii="${i}.meta"
        echo "将删除meta文件${ii}"
        ls | grep "$ii"
        rm -f "$ii"
        same=true
      fi
   done
done

if [ "$same" == false ]; then
   echo "No same elements"
fi
echo "######修改后目录：######"
find $CI_PROJECT_DIR -maxdepth 1 -type d -printf "%f\n"
echo "#########################"
