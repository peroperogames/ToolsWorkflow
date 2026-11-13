from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_layout_detection.sh")
t = p.read_text(encoding="utf-8")
t = t.replace('''# --- and the real repositories ---------------------------------------------------
for repo in CITest:.:accessking:Unity:pero-serde:Unity; do :; done
''', '''# --- and the real repositories ---------------------------------------------------
''')
p.write_text(t, encoding="utf-8", newline="\n")
print("cleaned")
