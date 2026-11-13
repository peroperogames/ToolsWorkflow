"""Delete GitHub Actions artifacts to free the account's storage quota.

Artifacts belong to runs, not to pull requests: closing a pull request frees nothing,
and neither does re-running a job. They are deleted explicitly (this script) or expire
per their retention setting.

Dry run by default — it prints what it would delete and the total it would free.

    python .scratch/prune_artifacts.py peroperogames/lazymeowcity --older-than 7
    python .scratch/prune_artifacts.py peroperogames/lazymeowcity --older-than 7 --delete
    python .scratch/prune_artifacts.py peroperogames/lazymeowcity --keep-last 20 --delete

Deleting an artifact frees its bytes; GitHub recalculates storage every 6-12 hours,
so a quota that was hit keeps refusing uploads for a while after the space is free.
"""

import argparse
import datetime as dt
import json
import subprocess
import sys


def gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit("gh %s failed: %s" % (" ".join(args), result.stderr.strip()))
    return result.stdout


def artifacts(repo: str) -> list:
    found, page = [], 1
    while True:
        data = json.loads(
            gh("api", "repos/%s/actions/artifacts?per_page=100&page=%d" % (repo, page))
        )
        batch = data.get("artifacts") or []
        found.extend(batch)
        if len(batch) < 100:
            return found
        page += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--older-than", type=int, default=7, metavar="DAYS")
    parser.add_argument("--keep-last", type=int, default=0, metavar="N",
                        help="keep the N newest artifacts whatever their age")
    parser.add_argument("--delete", action="store_true", help="actually delete")
    parser.add_argument("--name-contains", default="", help="only artifacts whose name contains this")
    args = parser.parse_args()

    found = artifacts(args.repo)
    if args.name_contains:
        found = [a for a in found if args.name_contains in (a.get("name") or "")]
    found.sort(key=lambda a: a.get("created_at") or "", reverse=True)

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.older_than)
    freed, deleted, kept_new = 0, 0, 0
    total = sum(a.get("size_in_bytes") or 0 for a in found)
    print("%s: %d artifact(s), %.1f MB" % (args.repo, len(found), total / 1048576))

    for index, artifact in enumerate(found):
        if index < args.keep_last:
            kept_new += 1
            continue
        created = dt.datetime.fromisoformat(
            (artifact.get("created_at") or "1970-01-01T00:00:00Z").replace("Z", "+00:00")
        )
        if created >= cutoff:
            continue
        size = artifact.get("size_in_bytes") or 0
        line = "  %-58s %8.2f MB  %s" % (
            (artifact.get("name") or "")[:58], size / 1048576,
            created.strftime("%Y-%m-%d"),
        )
        if args.delete:
            gh("api", "-X", "DELETE", "repos/%s/actions/artifacts/%s" % (args.repo, artifact["id"]))
            print(line + "  deleted")
        else:
            print(line + "  would delete")
        freed += size
        deleted += 1

    print(
        "%s: %d artifact(s), %.1f MB %s"
        % (args.repo, deleted, freed / 1048576, "deleted" if args.delete else "would free")
    )
    if args.delete and deleted:
        print("GitHub recalculates storage every 6-12 hours; the quota frees up then.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
