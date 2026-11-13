import io
import sys

PATH = r"E:\Gatongone\GitClone\ToolsWorkflow\review\main.py"
source = io.open(PATH, encoding="utf-8").read()

old = '''    lines = ["🔧 **重新构建与测试**", f"仓库类型：{kind_line}", ""]
    if extra_context:
        # The section as the model would see it, minus its heading: the same
        # words, from the same place.
        lines.append(extra_context.split("\\n\\n", 1)[-1])
    else:
        lines.append("没有构建/测试步骤运行——该仓库没有，或工具链不可用，详见日志。")
    if static_posted:
        lines.append(f"ReSharper：新提出 {static_posted} 条行内意见。")
    link = report_link_line()
    if link:
        lines.append(link)
    return "\\n".join(lines)'''

new = '''    # Blocks are separated by a blank line, because a line directly under a
    # markdown table is a row of that table: the .NET verdict and the ReSharper
    # line were rendering inside the Unity test table.
    blocks = [f"🔧 **重新构建与测试**\\n仓库类型：{kind_line}"]
    if extra_context:
        # The section as the model would see it, minus its heading: the same
        # words, from the same place.
        blocks.append(extra_context.split("\\n\\n", 1)[-1])
    else:
        blocks.append("没有构建/测试步骤运行——该仓库没有，或工具链不可用，详见日志。")
    if static_posted:
        blocks.append(f"ReSharper：新提出 {static_posted} 条行内意见。")
    link = report_link_line()
    if link:
        blocks.append(link)
    return "\\n\\n".join(blocks)'''

if source.count(old) != 1:
    sys.exit(f"anchor found {source.count(old)} times")
io.open(PATH, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
print("patched")
