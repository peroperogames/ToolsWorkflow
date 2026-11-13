from pathlib import Path
p = Path(r"E:\Gatongone\GitClone\ToolsWorkflow\.scratch\prune_artifacts.py")
t = p.read_text(encoding="utf-8")
old = '''    parser.add_argument("--workflow", default="", help="only this workflow file name")
    args = parser.parse_args()

    found = artifacts(args.repo)
    if args.workflow:
        found = [a for a in found if (a.get("workflow_run") or {}).get("head_branch") is not None
                 and a.get("name", "").find(args.workflow) >= 0 or True]
    found.sort(key=lambda a: a.get("created_at") or "", reverse=True)
'''
new = '''    parser.add_argument("--name-contains", default="", help="only artifacts whose name contains this")
    args = parser.parse_args()

    found = artifacts(args.repo)
    if args.name_contains:
        found = [a for a in found if args.name_contains in (a.get("name") or "")]
    found.sort(key=lambda a: a.get("created_at") or "", reverse=True)
'''
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
print("patched")
