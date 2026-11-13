import sys
from pathlib import Path
sys.path.insert(0, r"E:\Gatongone\GitClone\ToolsWorkflow\review")
import main

for body in ["@perotoolsbot settle", "@perotoolsbot settle\n", "  @perotoolsbot settle  ",
             "@perotoolsbot settle.", "@PerotoolsBot settle", "@perotoolsbot[bot] settle"]:
    for login in ["perotoolsbot[bot]", "perotoolsbot"]:
        cmd = main.parse_command(body, login)
        print(f"{body!r:40} login={login:20} -> {cmd.name if cmd else None}")
