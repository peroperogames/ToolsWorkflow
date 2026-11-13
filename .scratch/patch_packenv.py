from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.github\workflows\publish-npm.yml")
t = p.read_text(encoding="utf-8")
old = """        env:
          CI_COMMIT_TAG: ${{ github.ref_name }}
          NUGET_PROJECT: ${{ inputs.nuget-project }}
        run: |"""
new = """        env:
          CI_COMMIT_TAG: ${{ github.ref_name }}
        run: |"""
assert t.count(old) == 1, t.count(old)
t = t.replace(old, new)
p.write_text(t, encoding="utf-8", newline="\n")
print("pack env patched")
