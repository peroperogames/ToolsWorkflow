"""Local check: what a project's manifest gets before a package is added to it."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import unity_runner as u


def make_project(dependencies):
    root = Path(tempfile.mkdtemp(prefix="manifest-check-"))
    (root / "Packages").mkdir()
    (root / "Packages" / "manifest.json").write_text(
        json.dumps({"dependencies": dependencies}, indent=2), encoding="utf-8"
    )
    return root


def manifest(root):
    return json.loads((root / "Packages" / "manifest.json").read_text(encoding="utf-8"))


# A project fresh from the 3D template: the three packages the pipeline provides are
# absent, so all three are added at their minimums.
root = make_project({"com.unity.modules.ui": "1.0.0"})
u.prepare_manifest(str(root))
deps = manifest(root)["dependencies"]
print("--- a template project gets:")
for name in (u.TEST_FRAMEWORK, u.MOQ, u.NEWTONSOFT_JSON):
    print(f"    {name}: {deps.get(name)}")
assert deps[u.TEST_FRAMEWORK] == "1.4.6", deps
assert deps[u.MOQ] == "4.21.0", deps
assert deps[u.NEWTONSOFT_JSON] == "3.2.1", deps
assert deps["com.unity.modules.ui"] == "1.0.0", deps

# A project already carrying the packages: the rule is "raise, never lower".
root = make_project({
    u.TEST_FRAMEWORK: "1.4.6",
    u.MOQ: "4.20.0",
    u.NEWTONSOFT_JSON: "3.2.1",
})
u.prepare_manifest(str(root))
deps = manifest(root)["dependencies"]
assert deps[u.TEST_FRAMEWORK] == "1.4.6", deps
assert deps[u.MOQ] == "4.21.0", f"an older Moq should be raised: {deps}"
assert deps[u.NEWTONSOFT_JSON] == "3.2.1", deps
print("--- an older version is raised, an equal one is left alone")

root = make_project({u.NEWTONSOFT_JSON: "3.3.0", u.MOQ: "4.21.0", u.TEST_FRAMEWORK: "1.4.6"})
u.prepare_manifest(str(root))
assert manifest(root)["dependencies"][u.NEWTONSOFT_JSON] == "3.3.0", manifest(root)
print("--- a newer Newtonsoft.Json is kept")

# A repository's own reference is its business: file:/git: entries are not touched.
for value in ("file:../Newtonsoft.Json", "https://github.com/JamesNK/Newtonsoft.Json.git"):
    root = make_project({u.NEWTONSOFT_JSON: value, u.MOQ: "4.21.0", u.TEST_FRAMEWORK: "1.4.6"})
    u.prepare_manifest(str(root))
    assert manifest(root)["dependencies"][u.NEWTONSOFT_JSON] == value, manifest(root)
print("--- a file:/git reference is left alone")

# The scoped registries are still written, and Newtonsoft needs none of them.
root = make_project({})
u.prepare_manifest(str(root))
data = manifest(root)
registries = data.get("scopedRegistries") or []
names = {entry.get("name") for entry in registries}
assert "OpenUPM" in names, names
assert all("newtonsoft" not in json.dumps(entry).lower() for entry in registries), registries
print("--- the registries are unchanged, and Newtonsoft does not need one")

# Re-running it is a no-op: the manifest is byte-identical the second time.
before = (root / "Packages" / "manifest.json").read_text(encoding="utf-8")
u.prepare_manifest(str(root))
after = (root / "Packages" / "manifest.json").read_text(encoding="utf-8")
assert before == after, "a second run rewrote the manifest"
print("--- a second run changes nothing")
print("OK")
