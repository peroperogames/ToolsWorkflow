from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\patch_resolve_layout.py")
t = p.read_text(encoding="utf-8")
old = '''replace(
    """      - name: Resolve the publish channels
        id: channels
        run: |
          bash "$RUNNER_TEMP/devops/ToolsWorkflow/publish/resolve_channels.sh\\"""",'''
new = '''replace(
    """      - name: Resolve the publish channels
        id: channels
        env:
          CHANNELS: ${{ inputs.channels }}
          NUGET_PROJECT: ${{ inputs.nuget-project }}
          NUGET_USER: ${{ inputs.nuget-user }}
          NPM_URL: ${{ secrets.NPM_URL }}
        run: |
          bash "$RUNNER_TEMP/devops/ToolsWorkflow/publish/resolve_channels.sh\\"""",'''
assert t.count(old) == 1, t.count(old)
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
