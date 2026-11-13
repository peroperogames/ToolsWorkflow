from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_publish_workflow.py")
t = p.read_text(encoding="utf-8")
t = t.replace('"Resolve the publish channels",', '"Resolve the package directory and the NuGet project",')
t = t.replace('order["Resolve the publish channels"]', 'order["Resolve the package directory and the NuGet project"]')
p.write_text(t, encoding="utf-8", newline="\n")
print("patched")
