"""Local check: the Addressables provisioning step, in a real Unity project.

Runs the pipeline's own `ensure_project_settings` against the local 2022.3 project,
which is a package project with `com.unity.addressables` added to its manifest.
Creates the settings the way the runner will, then reads them back.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "review"))

import unity_runner

PROJECT = Path(r"E:\tmp\perolog-pr8\pero-pr8")
CLI = str(Path.home() / "AppData" / "Local" / "Unity" / "bin" / "unity.exe")
LOG = PROJECT.parent / "provision-test.log"

settings = PROJECT / unity_runner.ADDRESSABLE_SETTINGS
script = PROJECT / unity_runner.PROVISION_SCRIPT
print(f"project:  {PROJECT}")
print(f"settings before: {settings.is_file()}")
print(f"resolves addressables: {unity_runner._resolves_addressables(str(PROJECT))}")

unity_runner.ensure_project_settings(CLI, str(PROJECT), LOG)

print(f"script:   {script} exists={script.is_file()}")
print(f"settings after: {settings.is_file()}")
if settings.is_file():
    print(f"size: {settings.stat().st_size} bytes")
stamp = PROJECT / unity_runner.PROVISION_STAMP
print(f"stamp:    {stamp} -> {stamp.read_text(encoding='utf-8').strip() if stamp.is_file() else '(none)'}")
assert script.is_file(), "the provisioning script should be left where the editor found it"
assert settings.is_file(), f"no settings asset at {settings}"
assert unity_runner._provisioned(str(PROJECT)) == unity_runner.ADDRESSABLE_PLAYMODE, (
    "the play mode script the tests expect is not what the stamp records"
)

# The second call must not start another editor: the stamp is what makes every
# later run of the same project free.
import time

started = time.monotonic()
unity_runner.ensure_project_settings(CLI, str(PROJECT), LOG)
took = time.monotonic() - started
print(f"second call: {took:.1f}s")
assert took < 5, f"the second call launched the editor again ({took:.0f}s)"
print("OK")
