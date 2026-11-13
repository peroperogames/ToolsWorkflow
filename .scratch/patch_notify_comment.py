from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.github\workflows\publish-npm.yml")
t = p.read_text(encoding="utf-8")
old = """  # Only after every channel that ran came out green, and only for a release tag:
  # the variants are not releases anyone announces.
  notify:
    needs: [publish, external]
    if: >-
      # A release (`1.2.3`) and a base release (`1.2.3-base`) are announced; a
      # variant (`1.2.3-android-variant`) is a build of the same source for a
      # different target and is published to PeroNPM alone, unannounced.
      ${{ !cancelled()"""
new = """  # Only after every channel that ran came out green, and only for a release or a base
  # release: a variant is a build of the same source for another target, published to
  # PeroNPM alone, and nobody is told about it.
  notify:
    needs: [publish, external]
    if: >-
      ${{ !cancelled()"""
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
