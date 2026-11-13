"""Local check: the pipeline builds with the newest SDK the runner has.

PeroError PR #1 targets `net11.0`. The runner has two SDKs — the distribution's in
`/usr/bin` and 11.0.100 under `~/.dotnet` — and a job step's PATH only had the
first, so the build died with NETSDK1045 while `dotnet --version` in a shell said
11.0.100.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "review"))

import dotnet_runner

failures = []


def ok(msg):
    print("ok   " + msg)


def bad(msg):
    print("FAIL " + msg)
    failures.append(msg)


def version_of(mapping):
    return lambda path: mapping.get(path, ())


# 1. The two installs this runner really has: the newest wins, whatever PATH says.
chosen, seen = dotnet_runner.pick_newest_dotnet(
    ["/usr/bin/dotnet", "/home/actions/.dotnet/dotnet"],
    version_of(
        {"/usr/bin/dotnet": (10, 0, 103), "/home/actions/.dotnet/dotnet": (11, 0, 100)}
    ),
)
if chosen == "/home/actions/.dotnet/dotnet" and len(seen) == 2:
    ok("the newest SDK is chosen over the one first on PATH")
else:
    bad(f"chosen={chosen!r} seen={seen!r}")

# 2. A single install is used as it is.
chosen, _ = dotnet_runner.pick_newest_dotnet(
    ["/usr/bin/dotnet"], version_of({"/usr/bin/dotnet": (10, 0, 103)})
)
if chosen == "/usr/bin/dotnet":
    ok("a runner with one SDK builds with it")
else:
    bad(chosen)

# 3. An install that cannot say its version is not preferred over one that can.
chosen, seen = dotnet_runner.pick_newest_dotnet(
    ["/opt/broken/dotnet", "/usr/bin/dotnet"],
    version_of({"/usr/bin/dotnet": (10, 0, 103)}),
)
if chosen == "/usr/bin/dotnet" and seen[0][1] == ():
    ok("an unreadable install never wins")
else:
    bad(f"chosen={chosen!r} seen={seen!r}")

# 4. Nothing usable: the first candidate is returned rather than None, and the
#    caller still has something to try.
chosen, seen = dotnet_runner.pick_newest_dotnet(["/x/dotnet"], version_of({}))
if chosen == "/x/dotnet":
    ok("no version information still leaves a tool to run")
else:
    bad(chosen)

# 5. Versions compare as numbers, not as strings: 9 < 10.
chosen, _ = dotnet_runner.pick_newest_dotnet(
    ["/a/dotnet", "/b/dotnet"],
    version_of({"/a/dotnet": (9, 0, 100), "/b/dotnet": (10, 0, 100)}),
)
if chosen == "/b/dotnet":
    ok("10 beats 9, though '9' sorts after '10'")
else:
    bad(chosen)

# 6. Prerelease suffixes do not confuse the comparison.
if dotnet_runner._version_tuple("11.0.100-preview.1\n") == (11, 0, 100):
    ok("a prerelease version compares as its number")
else:
    bad(str(dotnet_runner._version_tuple("11.0.100-preview.1")))

print()
if failures:
    print("%d check(s) failed" % len(failures))
    sys.exit(1)
print("OK")
