"""One-off: the package directory and the NuGet project are found, not passed."""

import re
from pathlib import Path

root = Path(__file__).resolve().parent.parent
workflow = root / ".github" / "workflows" / "publish-npm.yml"
text = workflow.read_text(encoding="utf-8")


def replace(old: str, new: str) -> None:
    global text
    assert text.count(old) == 1, (text.count(old), old[:80])
    text = text.replace(old, new)


# 1. The two paths may be left out: the repository answers them.
replace(
    """      nuget-project:
        description: >-
          The .csproj or .sln the nuget channel packs, relative to the
          REPOSITORY ROOT — not to working-directory, because a package whose
          manifest lives in a subdirectory usually keeps its projects beside it
          rather than inside it. Only used when the nuget channel is named.
        required: false
        type: string
        default: ''""",
    """      nuget-project:
        description: >-
          The .csproj or .sln the nuget channel packs, relative to the REPOSITORY
          ROOT. Leave it empty and the project is found: the only one that is not
          IsPackable=false, or the solution that holds them. Only used when the nuget
          channel is named.
        required: false
        type: string
        default: ''""",
)
replace(
    """      working-directory:
        description: 'Subdirectory to cd into after checkout (relative to repo root). Defaults to repo root.'
        required: false
        type: string
        default: '.'""",
    """      working-directory:
        description: >-
          The package directory, relative to the repository root. Leave it empty and
          the package is found: the shallowest directory whose package.json has a name.
        required: false
        type: string
        default: ''""",
)

# 2. nuget-user is always this organisation's nuget.org profile.
replace(
    """      nuget-user:
        description: >-
          The nuget.org profile name the trusted publishing policy belongs to.
          Only used when the nuget channel is named.
        required: false
        type: string
        default: ''""",
    """      nuget-user:
        description: >-
          The nuget.org profile name the trusted publishing policy belongs to.
          Only used when the nuget channel is named.
        required: false
        type: string
        default: 'Peropero'""",
)

# 3. The job runs at the root; a step moves into the package itself.
replace(
    """    defaults:
      run:
        working-directory: ${{ inputs.working-directory }}""",
    """    # Steps run at the repository root and move into the package themselves: the
    # package directory is resolved by a step, and a job default cannot read a value
    # another step produced.
    defaults:
      run:
        working-directory: ${{ github.workspace }}""",
)

# 4. One step resolves all three, before anything is packed.
replace(
    """      - name: Resolve the publish channels
        id: channels
        env:
          CHANNELS: ${{ inputs.channels }}
          NUGET_PROJECT: ${{ inputs.nuget-project }}
          NUGET_USER: ${{ inputs.nuget-user }}
          NPM_URL: ${{ secrets.NPM_URL }}
        run: |
          bash "$RUNNER_TEMP/devops/ToolsWorkflow/publish/resolve_channels.sh\"""",
    """      - name: Resolve the package directory and the NuGet project
        id: channels
        env:
          HINT_DIR: ${{ inputs.working-directory }}
          HINT_NUGET: ${{ inputs.nuget-project }}
          HINT_USER: ${{ inputs.nuget-user }}
          CHANNELS: ${{ inputs.channels }}
          NPM_URL: ${{ secrets.NPM_URL }}
        run: |
          tools="$RUNNER_TEMP/devops/ToolsWorkflow/publish"

          # Where the package is. A caller may name it; the repository knows.
          PACKAGE_DIR=$(bash "$tools/package_dir.sh" "$GITHUB_WORKSPACE" "$HINT_DIR") || exit 1
          PACKAGE_ROOT="$GITHUB_WORKSPACE"
          if [ "$PACKAGE_DIR" != "." ]; then
            PACKAGE_ROOT="$GITHUB_WORKSPACE/$PACKAGE_DIR"
          fi
          echo "package directory: $PACKAGE_DIR"

          # What the nuget channel packs. Resolved only when that channel is on: a
          # release that does not publish to nuget.org has nothing to pack, and a
          # repository without a project is not an error for it.
          NUGET_PROJECT="$HINT_NUGET"
          if [ -z "$NUGET_PROJECT" ] && printf '%s' "$CHANNELS" | tr ',' ' ' | grep -qiw nuget; then
            NUGET_PROJECT=$(bash "$tools/nuget_project.sh" "$GITHUB_WORKSPACE") || exit 1
            echo "nuget-project: $NUGET_PROJECT"
          fi

          {
            echo "PACKAGE_DIR=$PACKAGE_DIR"
            echo "PACKAGE_ROOT=$PACKAGE_ROOT"
            echo "NUGET_PROJECT=$NUGET_PROJECT"
          } >> "$GITHUB_ENV"

          NUGET_USER="$HINT_USER" bash "$tools/resolve_channels.sh\"""",
)

# 5. The steps that ran inside the package directory move into it.
replace(
    """      - name: Package preprocess
        env:
          CI_COMMIT_TAG: ${{ github.ref_name }}
        run: |
          bash "$RUNNER_TEMP/devops/ToolsWorkflow/publish/package_preprocess.sh\"""",
    """      - name: Package preprocess
        env:
          CI_COMMIT_TAG: ${{ github.ref_name }}
        run: |
          cd "$PACKAGE_ROOT"
          bash "$RUNNER_TEMP/devops/ToolsWorkflow/publish/package_preprocess.sh\"""",
)
replace(
    """      - name: Publish to PeroNPM
        if: ${{ steps.channels.outputs.DO_PERONPM == 'true' }}
        run: |
          log="$RUNNER_TEMP/npm-publish-peronpm.log\"""",
    """      - name: Publish to PeroNPM
        if: ${{ steps.channels.outputs.DO_PERONPM == 'true' }}
        run: |
          cd "$PACKAGE_ROOT"
          log="$RUNNER_TEMP/npm-publish-peronpm.log\"""",
)
replace(
    """      - name: Collect the packages
        if: ${{ steps.channels.outputs.DO_NPMJS == 'true' || steps.channels.outputs.DO_NUGET == 'true' }}
        run: |
          rm -rf "$RUNNER_TEMP/publish-artifacts\"""",
    """      - name: Collect the packages
        if: ${{ steps.channels.outputs.DO_NPMJS == 'true' || steps.channels.outputs.DO_NUGET == 'true' }}
        run: |
          cd "$PACKAGE_ROOT"
          rm -rf "$RUNNER_TEMP/publish-artifacts\"""",
)

# 6. The folder-rename script reads CI_PROJECT_DIR; set it from the resolved root.
replace(
    """      - name: Change folder name
        env:
          CI_PROJECT_DIR: ${{ github.workspace }}/${{ inputs.working-directory }}
        run: |
          bash "$RUNNER_TEMP/devops/ToolsWorkflow/publish/changefoldername.sh\"""",
    """      - name: Change folder name
        run: |
          export CI_PROJECT_DIR="$PACKAGE_ROOT"
          bash "$RUNNER_TEMP/devops/ToolsWorkflow/publish/changefoldername.sh\"""",
)

# 7. Everything that read the input reads the resolved value instead.
pattern = re.compile(r"^\s*PACKAGE_DIR: \$\{\{ inputs\.working-directory \}\}\s*$")
lines, out, removed = text.split("\n"), [], 0
index = 0
while index < len(lines):
    line = lines[index]
    if pattern.match(line):
        removed += 1
        index += 1
        continue
    if re.match(r"^\s*env:\s*$", line):
        indent = len(line) - len(line.lstrip())
        following = lines[index + 1] if index + 1 < len(lines) else ""
        following_indent = len(following) - len(following.lstrip())
        # An env: whose only entry was PACKAGE_DIR is now empty, and a step should not
        # carry an empty one.
        if following.strip() and following_indent <= indent and not following.lstrip().startswith("- "):
            index += 1
            continue
    out.append(line)
    index += 1
text = "\n".join(out)
print(f"removed {removed} PACKAGE_DIR env line(s)")

# The input survives in exactly one place — the hint the resolve step reads.
leftovers = [l for l in text.split("\n") if "${{ inputs.working-directory }}" in l]
unexpected = [l for l in leftovers if "HINT_DIR:" not in l]
if unexpected or len(leftovers) != 1:
    print("UNEXPECTED:", leftovers)
    raise SystemExit(1)

workflow.write_text(text, encoding="utf-8", newline="\n")
print("patched")
