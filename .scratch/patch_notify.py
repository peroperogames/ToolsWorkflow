from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.github\workflows\publish-npm.yml")
t = p.read_text(encoding="utf-8")

old = """      ${{ !cancelled()
          && needs.publish.result == 'success'
          && (needs.external.result == 'success' || needs.external.result == 'skipped')
          && endsWith(github.ref_name, '-base') }}"""
new = """      # A version with no suffix is a release, and a release is announced. A
      # prerelease (`1.2.3-preview.1`) was announced by whoever published it, and it
      # reaches PeroNPM alone.
      ${{ !cancelled()
          && needs.publish.result == 'success'
          && (needs.external.result == 'success' || needs.external.result == 'skipped')
          && !contains(github.ref_name, '-') }}"""
assert t.count(old) == 1, t.count(old)
t = t.replace(old, new)

start = t.index("           # OpenUPM builds a package from a tag and takes the tag as the version, so")
end = t.index("      # npm shows the README that is inside the published tarball")
t = t[:start] + "\n" + t[end:]

anchor = "      # Only after every channel that ran came out green, and only for a `-base` tag:"
if anchor in t:
    t = t.replace(anchor, "      # Only after every channel that ran came out green, and only for a release:")
p.write_text(t, encoding="utf-8", newline="\n")
print("workflow patched")
