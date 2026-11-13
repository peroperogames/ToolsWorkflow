from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\publish\README.md")
t = p.read_text(encoding="utf-8")

def replace(old, new):
    global t
    assert t.count(old) == 1, (t.count(old), old[:60])
    t = t.replace(old, new)

replace(
    "| `nuget-project` | — | The `.csproj` or `.sln` the `nuget` channel packs, relative to the **repository root** — not to `working-directory`, because a package whose manifest lives in a subdirectory keeps its projects beside it, not inside it. A solution packs every project in it that is packable. |",
    "| `nuget-project` | the only packable project | The `.csproj` or `.sln` the `nuget` channel packs, relative to the **repository root**. Leave it empty and it is found: the one project without `IsPackable=false`, or the solution holding them when there is more than one. |",
)
replace(
    "| `nuget-user` | — | The nuget.org profile name the trusted publishing policy belongs to — the last path segment of `nuget.org/profiles/<name>`, not the package's owner display or the account's e-mail. `Peropero`, not `perotools`: a name with no profile there fails the login step, after the release has already packed. |",
    "| `nuget-user` | `Peropero` | The nuget.org profile name the trusted publishing policy belongs to — the last path segment of `nuget.org/profiles/<name>`. |",
)
replace(
    "| `working-directory` | `.` | Subdirectory to work in, relative to the repository root. |",
    "| `working-directory` | the package's own directory | Where the package is, relative to the repository root. Leave it empty and it is found: the shallowest directory whose `package.json` has a name, so a sample project nested deeper cannot be mistaken for the package. |",
)

anchor = "## OpenUPM\n"
assert t.count(anchor) == 1
section = """## What the caller does not have to say

Three things a caller used to name are answered by the repository, because they are the
same in every repository here and a wrong value fails late — as a version that silently
did not change:

- **the package directory** — the shallowest directory whose `package.json` has a name
  (`package_dir.sh`);
- **the project the nuget channel packs** — the only one that is not
  `IsPackable=false`, or the solution holding them when there is more than one
  (`nuget_project.sh`);
- **the nuget.org profile** — `Peropero`.

The first two are resolved in one step before anything is packed, written to `$GITHUB_ENV`
as `PACKAGE_DIR` (relative), `PACKAGE_ROOT` (absolute) and `NUGET_PROJECT`, and the steps
that work inside the package move into it themselves: a job default cannot read a value
another step produced. Naming any of them still works and wins over the guess.

`unity-plugin-project` is not one of them. Which assembly the Unity package ships can be
matched to a project, but the **configuration** it has to be built in cannot: AccessKing
compiles a different assembly in its `Unity` configuration than in `Release`, and a wrong
guess ships the wrong binary silently.

"""
t = t.replace(anchor, section + anchor)
p.write_text(t, encoding="utf-8", newline="\n")
print("patched")
