"""One-off: let CI create a package that does not exist yet, once, with a token.

npm attaches a trusted publisher to a package, so the first publish of a new name
cannot use OIDC — and a placeholder version is not acceptable either. One optional
secret does the bootstrap inside the workflow, and every release after it is OIDC.
"""

from pathlib import Path

root = Path(__file__).resolve().parent.parent
workflow = root / ".github" / "workflows" / "publish-npm.yml"
readme = root / "publish" / "README.md"

text = workflow.read_text(encoding="utf-8")


def replace(old: str, new: str) -> None:
    global text
    assert text.count(old) == 1, (text.count(old), old[:70])
    text = text.replace(old, new)


# 1. The optional secret.
replace(
    """      NPM_URL:
        required: false  # PeroNPM registry URL — the peronpm channel""",
    """      NPM_URL:
        required: false  # PeroNPM registry URL — the peronpm channel
      # Optional, and only for the FIRST release of a package that is not on
      # npmjs yet: npm attaches a trusted publisher to a package, so there is
      # nothing to trust until the package exists. A granular token with publish
      # rights creates it once; every release after that uses OIDC, and the secret
      # is deleted.
      NPMJS_BOOTSTRAP_TOKEN:
        required: false""",
)

# 2. The step reads it.
replace(
    """      - name: Publish to npmjs
        if: ${{ needs.publish.outputs.npmjs == 'true' }}
        run: |""",
    """      - name: Publish to npmjs
        if: ${{ needs.publish.outputs.npmjs == 'true' }}
        env:
          NPMJS_BOOTSTRAP_TOKEN: ${{ secrets.NPMJS_BOOTSTRAP_TOKEN }}
        run: |""",
)

# 3. The fallback, after the OIDC attempts have failed.
replace(
    """            echo "Attempt $i failed, retrying in 5 seconds..."
            sleep 5
          done
          exit 1

      # Requested right before the push: nuget.org hands out a key valid for one""",
    """            echo "Attempt $i failed, retrying in 5 seconds..."
            sleep 5
          done

          # The first publish of a package that does not exist cannot use OIDC: a
          # trusted publisher is attached to a package, so there is nothing to
          # trust yet. One token creates it, once — every release after that is
          # OIDC, and the secret is meant to be deleted right after this one.
          if [ -n "${NPMJS_BOOTSTRAP_TOKEN:-}" ]; then
            echo "::warning::The trusted publish did not go through. Creating the package once with NPMJS_BOOTSTRAP_TOKEN; delete that secret after this release."
            userconfig="$RUNNER_TEMP/npm-bootstrap.npmrc"
            printf '//registry.npmjs.org/:_authToken=%s\\n' "$NPMJS_BOOTSTRAP_TOKEN" > "$userconfig"
            if npm publish "$tarball" --registry https://registry.npmjs.org/ --userconfig "$userconfig" > "$log" 2>&1; then
              rm -f "$userconfig"
              cat "$log"
              echo "The package now exists on registry.npmjs.org. Every later release publishes through OIDC; delete NPMJS_BOOTSTRAP_TOKEN."
              exit 0
            fi
            rm -f "$userconfig"
            cat "$log"
            if grep -qE 'E409|EPUBLISHCONFLICT|cannot publish over' "$log"; then
              echo "This version is already on registry.npmjs.org; nothing to publish."
              exit 0
            fi
            echo "::error::The bootstrap publish failed as well — the token may not be allowed to create this package."
          fi
          exit 1

      # Requested right before the push: nuget.org hands out a key valid for one""",
)

workflow.write_text(text, encoding="utf-8", newline="\n")

# 4. Docs.
doc = readme.read_text(encoding="utf-8")
old = """The two extra channels are opt-in and stay opt-in:"""
new = """**The first release of a new npm package needs one token, once.** npm attaches a
trusted publisher to a package, so a package that does not exist has nothing to
trust — and a tokenless publish cannot create one. `NPMJS_BOOTSTRAP_TOKEN` (repo
secret, granular token with publish rights) is read only after the trusted publish
has failed: it creates the package once, the step says so in the log, and every
release after that goes through OIDC. Delete the secret after that first release. A
`0.0.0` placeholder version is the other way to create the package, and it stays in
the version history forever — which is why this exists.

The two extra channels are opt-in and stay opt-in:"""
assert doc.count(old) == 1
doc = doc.replace(old, new, 1)

old_secret = "| `NPM_URL` | only for `peronpm` | The PeroNPM registry URL. |"
new_secret = (
    old_secret
    + "\n| `NPMJS_BOOTSTRAP_TOKEN` | no | A granular npm token, used only to create a package that does not exist on npmjs yet. Delete it after that release. |"
)
assert doc.count(old_secret) == 1
doc = doc.replace(old_secret, new_secret, 1)
readme.write_text(doc, encoding="utf-8", newline="\n")
print("patched")
