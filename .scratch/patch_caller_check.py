from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\check_accessking_caller.py")
t = p.read_text(encoding="utf-8")
start = t.index("# The state this replaces:")
end = t.index('print()\nif failures:')
new = '''# Each channel owns its prerequisites: take away what nuget needs and the resolver
# says which input, by name, before anything has been built.
env["CHANNELS"] = "nuget"
env["NUGET_PROJECT"] = ""
missing = subprocess.run(["bash", resolver], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", executable=BASH)
said = missing.stdout + missing.stderr
if missing.returncode != 0 and "nuget-project" in said:
    ok("a channel missing its inputs is refused by name")
else:
    bad("the resolver accepts nuget with no nuget-project (exit %d)" % missing.returncode)

'''
p.write_text(t[:start] + new + t[end:], encoding="utf-8", newline="\n")
print("patched")
