from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\patch_resolve_layout2.py")
t = p.read_text(encoding="utf-8")
old = """leftovers = [l for l in text.split("\\n") if "${{ inputs.working-directory }}" in l]
if leftovers:
    print("LEFTOVERS:", leftovers)
    raise SystemExit(1)"""
new = '''# The input survives in exactly one place — the hint the resolve step reads.
leftovers = [l for l in text.split("\\n") if "${{ inputs.working-directory }}" in l]
unexpected = [l for l in leftovers if "HINT_DIR:" not in l]
if unexpected or len(leftovers) != 1:
    print("UNEXPECTED:", leftovers)
    raise SystemExit(1)'''
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
