# Publish

The reusable `publish-npm.yml` turns a release tag into a published package: it
rewrites the version wherever the repository writes it down, commits that, and then
publishes to the registries the caller asks for.

```yaml
# .github/workflows/publish.yml  (in the package repository)
name: Publish

on:
  release:
    types: [published]

jobs:
  publish:
    uses: peroperogames/ToolsWorkflow/.github/workflows/publish-npm.yml@main
    with:
      channels: peronpm
    secrets:
      NPM_URL: ${{ secrets.NPM_URL }}
      APP_ID: ${{ secrets.APP_ID }}
      APP_PK: ${{ secrets.APP_PK }}
      FEISHU_WEBHOOK: ${{ secrets.FEISHU_WEBHOOK }}
      FEISHU_SECRET: ${{ secrets.FEISHU_SECRET }}
```

That caller is the whole of the default: one channel, and nothing else to pass.

## Channels

`channels` is a comma-separated list. **PeroNPM is the default**, because it is the
registry these packages are read from, so it is what a release publishes when the
caller says nothing at all. The repositories that already call this workflow need no
change: they get `peronpm`, which is what they publish today.

| Channel | Publishes | Needs |
| --- | --- | --- |
| `peronpm` | The npm package to the PeroNPM registry (`NPM_URL`), which is where OpenUPM and the install snippets read it from. | The `npm login` that already lives in the runner user's `~/.npmrc`, and `NPM_URL`. |
| `npmjs` | The same tarball to `registry.npmjs.org`. | `NPMJS_TOKEN`, an npm token with publish rights on the package name. |
| `nuget` | `dotnet pack` of the project the caller names, pushed to a NuGet feed (`nuget.org` unless `nuget-source` says otherwise). | `nuget-project`, `NUGET_API_KEY`, and a .NET SDK on the runner. |

```yaml
    with:
      channels: peronpm,npmjs,nuget
      nuget-project: Core/PeroTools2.AccessKing.Core.csproj
```

The two extra channels are opt-in and stay opt-in: publishing to somebody else's
registry cannot be taken back, so nothing arrives there because a default drifted.
A channel name that is not in the table above fails the run before anything is
built — publishing to PeroNPM because `npmjs` was misspelled would be the worst of
both.

A list without `peronpm` is legal and means exactly that: `channels: nuget` uploads
to NuGet and nothing else, with no npm package for the release. Each channel owns
its credentials, and none of the three is declared required by the workflow — a
required secret fails the caller before it runs, so a caller that publishes to one
registry would be forced to hold the others'. What a channel is missing is reported
by `resolve_channels.sh`, by name, before anything is built.

`secrets: inherit` passes `NPMJS_TOKEN` and `NUGET_API_KEY` along with the rest if
the caller's environment holds them under those names.

## The version, and where it is written down

The tag names the version, and one rule reads it — `publish/version_from_tag.sh`,
sourced by both the packaging and the NuGet step, so a release cannot publish two
different versions of itself:

| Tag | Version |
| --- | --- |
| `0.3.0-base` | `0.3.0` |
| `v0.3.0-base` | `0.3.0` |
| `0.3.0-android-variant` | `0.3.0-android-variant` |
| anything else | the run stops, naming the tag |

That version is then written into every place the repository repeats it:

1. `package.json` — `version`, and the package name is moved under
   `expected-package-prefix` if it is not already there.
2. `README.md` — only the lines that name this package: the `"pkg": "x.y.z"` of an
   install snippet becomes the version, and a `git#…` reference becomes the tag
   itself, because `0.3.0` and `0.3.0-base` are not the same string to a consumer.
   Other packages' versions on the same page are left alone.
3. `*.csproj`, `*.props`, `*.targets` — `<Version>`, `<PackageVersion>` and
   `<InformationalVersion>` become the version; `<AssemblyVersion>` and
   `<FileVersion>` become its numeric core (`0.3.0`, also for
   `0.3.0-android-variant`), because those two cannot carry a prerelease label.

All of it lands in one commit, `chore: update package version to <version>.`, on the
branch the release was cut from. The commit is made with `--only` and the exact
paths above, because the packaging has already moved folders and deleted `.meta`
files in the working tree and anything else staged at that moment must not be swept
in. If nothing needs rewriting the commit is skipped and the run carries on.

## What the run does, in order

| Step | What and why |
| --- | --- |
| Resolve the publish channels | Validates `channels` and the credentials for the channels it names, and prints `Publishing to: …`. Everything after this reads the three flags it sets. |
| Pack the NuGet packages | Runs before the folders are renamed: `changefoldername.sh` puts a `~` on the folders `package.json` refers to, so a project inside one would no longer be at the path the repository names. The version is passed on the command line, which is a global property and therefore wins over the properties that are only bumped later. |
| Change folder name, Package preprocess, Update the README's version, Update the assembly version properties | The packaging and the version rewrite, see above. |
| Commit version update, Push changes | The one commit, rebased onto the branch tip so the push is a fast-forward, then the tag is moved to it. |
| Check npm auth | `npm whoami` against each registry the run will publish to, so a missing login fails here instead of after three publish attempts. |
| Publish to PeroNPM / Publish to npmjs / Push the NuGet packages | One step per channel, each gated on its own channel flag, each retried three times. |
| Send Feishu notification | Only for a `-base` tag, and only when everything succeeded. |
| Clean up the ci_cd checkout | Always, and it also removes the scratch npmjs `.npmrc` (it holds a token) and the packed `.nupkg` files. |

Steps that need Node are skipped when neither npm channel is on: a NuGet-only
release never sets up Node.

## Inputs

| Input | Default | Description |
| --- | --- | --- |
| `channels` | `peronpm` | Comma-separated list of `peronpm`, `npmjs`, `nuget`. |
| `nuget-project` | — | The `.csproj` or `.sln` the `nuget` channel packs, relative to `working-directory`. A solution packs every project in it that is packable. |
| `nuget-source` | `https://api.nuget.org/v3/index.json` | The feed the `nuget` channel pushes to. |
| `expected-package-prefix` | `com.prpr` | Package name prefix the manifest is moved under. |
| `node-version` | `20` | Node.js used to pack and publish. |
| `working-directory` | `.` | Subdirectory to work in, relative to the repository root. |

| Secret | Required | Description |
| --- | --- | --- |
| `APP_ID`, `APP_PK` | yes | The `PeroToolsBot` GitHub App, used for the token that clones this repository and pushes the version commit. |
| `FEISHU_WEBHOOK`, `FEISHU_SECRET` | yes | The notification for `-base` releases. |
| `NPM_URL` | only for `peronpm` | The PeroNPM registry URL. |
| `NPMJS_TOKEN` | only for `npmjs` | npm token for `registry.npmjs.org`, publish scope. |
| `NUGET_API_KEY` | only for `nuget` | NuGet API key with push scope on the package id. |

## Notes that save an afternoon

- **Another registry's token never goes in `~/.npmrc`.** That file holds the PeroNPM
  login on these runners, so the npmjs token is written to `$RUNNER_TEMP/npmrc-npmjs`
  (mode `600`) and handed to npm with `--userconfig`. Overwriting the shared login
  would break the next PeroNPM release with an auth error naming the wrong registry.
- **A scoped name publishes with `--access public`.** Without it npm treats a
  `@scope/name` as private and fails on an account that has no private packages.
- **`--skip-duplicate` makes a re-run safe.** Re-running a release whose NuGet
  package is already in the feed succeeds instead of failing on the version that
  exists; the npm steps still fail on an already-published version.
- **An empty pack is a failure.** `dotnet pack` on a project with
  `IsPackable=false` — a test project, usually — produces nothing, and a step that
  pushes nothing must not report success.
- **The pack needs a .NET SDK on the runner.** The job checks for `dotnet` and says
  so by name rather than failing inside MSBuild.
- **Tokens, not trusted publishing.** nuget.org and npm now accept OIDC ("trusted
  publishing") instead of a stored key, which is what Gneedle's workflow uses — but
  it needs `id-token: write` in *every* caller and a recent npm on the runner, so
  the six repositories that call this workflow unchanged would each have to be
  edited. A token keeps the callers as they are, and `secrets: inherit` already
  carries it.
