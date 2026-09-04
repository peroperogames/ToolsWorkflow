#!/bin/bash

# JSON 转义
json_escape() {
    local string="$1"
    local escaped=""
    local char
    local i

    for ((i=0; i<${#string}; i++)); do
        char="${string:$i:1}"
        case "$char" in
            '"')  escaped="${escaped}\\\"" ;;
            '\')  escaped="${escaped}\\\\" ;;
            $'\b') escaped="${escaped}\\b" ;;
            $'\f') escaped="${escaped}\\f" ;;
            $'\n') escaped="${escaped}\\n" ;;
            $'\r') escaped="${escaped}\\r" ;;
            $'\t') escaped="${escaped}\\t" ;;
            *)    escaped="${escaped}${char}" ;;
        esac
    done

    printf '%s' "$escaped"
}

# 检查参数数量
if [ "$#" -ne 6 ]; then
    echo "Need 6 parameters, but got $#."
    echo "Usage: $0 <webhook_url> <secret> <project_name> <tag> <description> <readme_url>"
    exit 1
fi

# 读取参数
WEBHOOK_URL="$1"
SECRET="$2"
PROJECT_NAME=$(json_escape "$3")
TAG=$(json_escape "$4")
DESCRIPTION=$(json_escape "$5")
README_URL=$(json_escape "$6")

# 时间戳（秒级）
TIMESTAMP=$(date +%s)

# 签名
STRING_TO_SIGN=$(printf "%s\n%s" "$TIMESTAMP" "$SECRET")
SIGN=$(echo -n "" | openssl dgst -sha256 -hmac "${STRING_TO_SIGN}" -binary | base64)

JSON_PAYLOAD=$(cat <<EOF
{
    "timestamp": "${TIMESTAMP}",
    "sign": "${SIGN}",
    "msg_type": "interactive",
    "card": {
        "config": {
            "wide_screen_mode": true
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "🚀 项目 ${PROJECT_NAME} 新版本发布"
            },
            "template": "blue"
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "**Version/Tag:** \`${TAG}\`\n\n**Release 说明:**\n${DESCRIPTION}"
                }
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "查看 README 文档详情"
                        },
                        "url": "${README_URL}",
                        "type": "primary"
                    }
                ]
            }
        ]
    }
}
EOF
)

# 发送请求并保存响应
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${WEBHOOK_URL}" \
    -H "Content-Type: application/json" \
    -d "${JSON_PAYLOAD}")

# 分离响应体和 HTTP 状态码
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
RESPONSE_BODY=$(echo "$RESPONSE" | sed '$d')

echo "$RESPONSE_BODY"

# 检查 HTTP 状态码
if [ "$HTTP_CODE" -ne 200 ]; then
    echo "Error: HTTP status code is $HTTP_CODE" >&2
    exit 1
fi

# 检查飞书 API 返回的 code 字段
API_CODE=$(echo "$RESPONSE_BODY" | grep -o '"code":[0-9]*' | head -1 | cut -d':' -f2)

if [ -z "$API_CODE" ]; then
    echo "Error: Unable to parse API response code" >&2
    exit 1
fi

if [ "$API_CODE" -ne 0 ]; then
    echo "Error: Feishu API returned error code $API_CODE" >&2
    exit 1
fi

echo "Message sent successfully!"
exit 0