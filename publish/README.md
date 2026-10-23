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
  call-publish:
    uses: peroperogames/ToolsWorkflow/.github/workflows/publish-npm.yml@main
    permissions:
      contents: write   # the version commit
      id-token: write   # OIDC, for npmjs and nuget.org
    with:
      channels: peronpm
    secrets:
      APP_ID: ${{ secrets.APP_ID }}
      APP_PK: ${{ secrets.APP_PK }}
      FEISHU_WEBHOOK: ${{ secrets.FEISHU_WEBHOOK }}
      FEISHU_SECRET: ${{ secrets.FEISHU_SECRET }}
      NPM_URL: ${{ secrets.NPM_URL }}
```

That caller is the whole of the default: one channel, and nothing else to pass.
`permissions:` is what makes the two extra channels possible at all — see
[The two runners](#the-two-runners).

## Channels

`channels` is a comma-separated list. **PeroNPM is the default**, because it is the
registry these packages are read from, so it is what a release publishes when the
caller says nothing at all. The repositories that already call this workflow need no
change to keep publishing to PeroNPM alone.

| Channel | Publishes | Authenticates with |
| --- | --- | --- |
| `peronpm` | The npm package to the PeroNPM registry (`NPM_URL`), which is where OpenUPM and the install snippets read it from. | The `npm login` that already lives in the runner user's `~/.npmrc`. |
| `npmjs` | The same tarball to `registry.npmjs.org`. | OIDC trusted publishing — no token, nothing to rotate. |
| `nuget` | `dotnet pack` of the project the caller names, pushed to a NuGet feed (`nuget.org` unless `nuget-source` says otherwise). | OIDC trusted publishing through `NuGet/login`. |

```yaml
    with:
      channels: peronpm,npmjs,nuget
      nuget-project: Core/PeroTools2.AccessKing.Core.csproj
      nuget-user: perotools
```

The two extra channels are opt-in and stay opt-in: publishing to somebody else's
registry cannot be taken back. A channel name that is not in the table above fails
the run before anything is built — publishing to PeroNPM because `npmjs` was
misspelled would be the worst of both.

A list without `peronpm` is legal and means exactly that: `channels: nuget` uploads
to NuGet and nothing else. Each channel owns its prerequisites, so a caller that
uses one need not supply the others'; what a channel is missing is reported by
`resolve_channels.sh`, by name, before anything is built.

## What goes where

The npm channels and the NuGet channel carry **different artifacts from the same
release**, and nothing is published to the wrong one:

| Artifact | Where it comes from | Who gets it |
| --- | --- | --- |
| The Unity package — the tarball of `working-directory`, exactly what `npm pack` produces there | `npm pack` after the version bump | PeroNPM and npmjs (the same bytes) |
| The .NET package(s) | `dotnet pack` of `nuget-project` | nuget.org |
| The shared library the Unity package ships, if it ships a precompiled one | a committed file under the package (`Unity/Plugins/…` in AccessKing), copied there by that project's own build | inside the Unity tarball only |

The third row is the one to watch: the publish bumps `<AssemblyVersion>` in the
project but never rebuilds that committed assembly, so a package built from a stale
copy ships an older binary than the NuGet package of the same version. AccessKing's
`Core` project already has a `CopyToUnityPackage` target for this — running

```bash
dotnet build Core/PeroTools2.AccessKing.Core.csproj -c Unity
```

before the release refreshes `Unity/Plugins/` (the DLL, its `.pdb` and its `.xml`),
and the resulting files belong in the same commit as the version bump. Making the
publish do that automatically is one input away if it turns out to be wanted.

## The two runners

The work is split over two jobs because it has to be:

| Job | Runs on | Does |
| --- | --- | --- |
| `publish` | the self-hosted runners (`build-server`, `unitypkg-share`) | the version bump, the commit and push, the PeroNPM publish, and packing the artifacts the other registries receive |
| `external` | `ubuntu-latest` | publishes those artifacts to npmjs and nuget.org over OIDC |
| `notify` | `ubuntu-latest` | the Feishu message, once both of the above are green |

**npm trusted publishing does not accept self-hosted runners.** npm's docs list
GitHub Actions "GitHub-hosted runners" as the supported case and say self-hosted
support is still planned, so a package published from our own runners can never
authenticate with OIDC — it can only fall back to a token, which is the thing being
retired. That single constraint is why the two channels live in a second job on a
GitHub-hosted runner, and why that job receives packages as artifacts instead of
building them.

`id-token: write` has to come from the **calling** job. GitHub only issues an OIDC
token to a job that asks for it, and a called workflow cannot grant itself
permission the caller did not give; without it the `external` job stops at its first
step with a message saying so.

## Set up once per repository

Three things live in the calling repository, and none of them can be done from this
one.

1. **`permissions: id-token: write`** on the calling job, as in the example above.

2. **`repository.url` in `package.json`** must name the GitHub repository —
   `https://github.com/peroperogames/<repo>` — because npm refuses a trusted publish
   whose manifest points somewhere else (it reports `E422`, and the message talks
   about provenance rather than the field). The publish warns about a missing or
   mismatched value as soon as it can read the tarball.

3. **The trusted publisher**, on the package's page:
   - **npmjs**: `npmjs.com` → the package → Settings → Trusted publishing → GitHub
     Actions. Fill in Organization or user (`peroperogames`), Repository, and
     **Workflow filename = the CALLING workflow's file** (`publish.yml`, name only,
     no path). Environment may stay empty. Then tick the allowed actions: **npm
     publish** (and, if wanted, `npm dist-tag`). New configurations default to
     staging only, and a `npm publish` from CI against such a publisher is refused —
     with `npm publish` ticked the release is unattended, without it every release
     waits for a maintainer's 2FA approval through `npm stage approve`. That is a
     real choice, not a formality.
   - **nuget.org**: `nuget.org` → username → Trusted Publishing → Add policy.
     Repository Owner, Repository, Workflow File (**file name only**, e.g.
     `publish.yml`), optional Environment, and the scope: **publish new packages**
     and **publish new versions**, with a glob for the package ids if wanted.

For a `workflow_call`, both registries validate the **calling** workflow's file
rather than this one — that is npm's documented behaviour, and it is what the
`external` job prints before it publishes:

```
calling workflow: peroperogames/AccessKing/.github/workflows/publish.yml@refs/tags/0.4.0-base
this job's file:  peroperogames/ToolsWorkflow/.github/workflows/publish-npm.yml@refs/heads/main
```

The claims are decoded from the OIDC token the job mints, so that line is exactly
what the registry sees. **A new npm trusted publisher must complete its first
successful publish within two days**, or the configuration expires and has to be
created again.

## The first release of a package

A trusted publisher is configured on the package's page, so the package has to exist
first. The first publish of each package is therefore done by hand, once, from the
exact artifact the release built:

1. Release with `channels: peronpm`. Every run uploads `publish-packages` as an
   artifact, so nothing extra is needed for this step.
2. Download `com.prpr.<name>-<version>.tgz` from the run.
3. On a machine with your npm login: `npm publish ./com.prpr.<name>-<version>.tgz`
   (2FA prompt, no token involved).
4. Configure the trusted publisher as above, and tick **npm publish**.
5. Publish a release within two days, or the configuration expires.
6. After a tokenless release is green, set the package's Settings → Publishing
   access to **"Require two-factor authentication and disallow tokens"**.

Doing it this way keeps the first publish and every later one the same bytes, and
never creates a long-lived credential. npm is retiring the old path anyway: bypass-2FA
tokens with direct-publish access lose the ability to publish new versions in
**January 2027**, and its own token page now steers you to "Read and write (stage
only)".

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
   `expected-package-prefix` if it is not already there. (A publish with no prefix
   at all is refused: it would name the package `.com.prpr.accessking`.)
2. `README.md` — only the lines that name this package: the `"pkg": "x.y.z"` of an
   install snippet becomes the version, and a `git#…` reference becomes the tag
   itself, because `0.3.0` and `0.3.0-base` are not the same string to a consumer.
   Other packages' versions on the same page are left alone. Both READMEs are
   looked at — the package's own, which npm shows, and the repository's, which is
   where a package whose manifest lives in a subdirectory usually writes its
   install snippets.
3. `*.csproj`, `*.props`, `*.targets` — `<Version>`, `<PackageVersion>` and
   `<InformationalVersion>` become the version; `<AssemblyVersion>` and
   `<FileVersion>` become its numeric core (`0.3.0`, also for
   `0.3.0-android-variant`), because those two cannot carry a prerelease label.
   The scan covers the whole repository, not just `working-directory`: the .NET
   side of a package sits beside the package directory rather than inside it
   (AccessKing's manifest is in `Unity/`, its project at `Core/`).

All of it lands in one commit, `chore: update package version to <version>.`, on the
branch the release was cut from. The commit is made with `--only` and the exact
paths above, because the packaging has already moved folders and deleted `.meta`
files in the working tree and anything else staged at that moment must not be swept
in. If nothing needs rewriting the commit is skipped and the run carries on.

Those three steps — the two rewrites and the commit — run from the **repository
root**, with the manifest read through `working-directory`. Git resolves a
pathspec against the current directory, so a bump that has to name `Unity/package.json`
and `Core/…csproj` in the same commit cannot run from inside `Unity/`.

## What the run does, in order

| Step (job) | What and why |
| --- | --- |
| Resolve the publish channels (`publish`) | Validates `channels` and what each named channel needs, prints `Publishing to: …`, and hands the three flags to the other jobs as this job's outputs. |
| Pack the NuGet packages (`publish`) | Runs before the folders are renamed: `changefoldername.sh` puts a `~` on the folders `package.json` refers to, so a project inside one would no longer be at the path the repository names. The version is passed on the command line, which is a global property and therefore wins over the properties that are only bumped later. |
| Change folder name, Package preprocess, Update the README's version, Update the assembly version properties (`publish`) | The packaging and the version rewrite, see above. The rewrites run from the repository root so the .NET project and the repository README are reachable. |
| Commit version update, Push changes (`publish`) | The one commit, rebased onto the branch tip so the push is a fast-forward, then the tag is moved to it. |
| Check the PeroNPM login, Publish to PeroNPM (`publish`) | `npm whoami` first, so a missing login fails here instead of after three publish attempts. |
| Collect the packages, Upload the packages (`publish`) | `npm pack` of the packaged tree plus the `.nupkg` files, into one `publish-packages` artifact. This is also what you download for a first, manual publish. |
| Report the identity this job publishes under (`external`) | Decodes the OIDC claims and prints the repository and both workflow refs, so a trusted publisher can be filled in from a run rather than guessed. |
| Publish to npmjs (`external`) | Checks that npm is 11.5.1 or newer (raising it if not), warns about `repository.url`, then `npm publish <tarball>` three times at most. No credential is passed in. |
| NuGet login, Push the NuGet packages (`external`) | `NuGet/login` exchanges the job's identity for an API key valid for one hour and one use, then `dotnet nuget push --skip-duplicate`, three attempts each. |
| Send Feishu notification (`notify`) | Only for a `-base` tag, and only when every channel that ran came out green. |

Each `publish` step is gated on its own channel flag from the resolver; the
`external` steps are gated on the flags the `publish` job reports. A channel that is
off runs nothing at all — a NuGet-only release never sets up Node.

## Inputs

| Input | Default | Description |
| --- | --- | --- |
| `channels` | `peronpm` | Comma-separated list of `peronpm`, `npmjs`, `nuget`. |
| `nuget-project` | — | The `.csproj` or `.sln` the `nuget` channel packs, relative to the **repository root** — not to `working-directory`, because a package whose manifest lives in a subdirectory keeps its projects beside it, not inside it. A solution packs every project in it that is packable. |
| `nuget-user` | — | The nuget.org profile name the trusted publishing policy belongs to. |
| `nuget-source` | `https://api.nuget.org/v3/index.json` | The feed the `nuget` channel pushes to. |
| `expected-package-prefix` | `com.prpr` | Package name prefix the manifest is moved under. |
| `node-version` | `20` | Node.js used to pack and publish to PeroNPM. The npmjs job pins its own, because trusted publishing needs a newer npm. |
| `working-directory` | `.` | Subdirectory to work in, relative to the repository root. |

| Secret | Required | Description |
| --- | --- | --- |
| `APP_ID`, `APP_PK` | yes | The `PeroToolsBot` GitHub App, used for the token that clones this repository and pushes the version commit. |
| `FEISHU_WEBHOOK`, `FEISHU_SECRET` | yes | The notification for `-base` releases. |
| `NPM_URL` | only for `peronpm` | The PeroNPM registry URL. |

There is no `NPMJS_TOKEN` and no `NUGET_API_KEY`: both registries are authenticated
with the job's own OIDC identity, which cannot leak and needs no rotation.

## Notes that save an afternoon

- **Provenance comes for free, except it does not, here.** A trusted publish from
  GitHub Actions attaches a provenance attestation automatically — but only for a
  public repository. These package repositories are private, so npmjs gets the
  package without the badge; nothing has to be configured either way, and
  `--provenance` is deliberately not passed (on a private repository it fails).
- **A private repository's first nuget.org policy is provisional.** nuget.org keeps
  a new policy "temporarily active" for seven days and locks it to the repository's
  immutable ids only after a successful publish; if none happens in that window it
  goes inactive until a publish restarts it.
- **The NuGet key expires in an hour and works once**, which is why the login step
  sits immediately before the push rather than at the top of the job.
- **`--skip-duplicate` makes a re-run safe.** Re-running a release whose NuGet
  package is already in the feed succeeds instead of failing on the version that
  exists; the npm publish still fails on an already-published version.
- **An empty pack is a failure.** `dotnet pack` on a project with
  `IsPackable=false` — a test project, usually — produces nothing, and a step that
  pushes nothing must not report success.
- **A scoped npmjs name has to be public.** Unscoped names like `com.prpr.accessking`
  publish publicly by default; a `@scope/name` would need `--access public`, which
  the publish does not pass — these packages are unscoped.
- **The first publish needs the package to exist**, which is the manual step
  described above; it cannot be automated away without a token, and tokens are the
  thing being retired.
