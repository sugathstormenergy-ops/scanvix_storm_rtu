"""
TEST-ONLY stand-in for sqlcmd, used by test_migration_detection.py to drive the REAL
PowerShell deploy module (scripts/deploy/StormRtu.psm1) without SQL Server.

It answers the module's catalog queries from a JSON state file (FAKE_SQL_STATE) and, like
the real sqlcmd, cuts every variable-length column to 256 characters in its text output
(sqlcmd's default -y display width) - the behaviour that broke migration detection live.
`-i <file>` runs are recorded (with the STORM_APP_LOGIN scripting variable) and the objects
the script creates are added to the state, so a second run sees them.
"""
import json
import os
import re
import sys

DISPLAY_WIDTH = 256
state_path = os.environ["FAKE_SQL_STATE"]
state = json.load(open(state_path))
args = sys.argv[1:]


def out(*cols):
    print("|".join(str(c)[:DISPLAY_WIDTH] for c in cols))


def objects_in(path):
    text = re.sub(r"--[^\r\n]*", "", open(path, encoding="utf-8").read())
    keys = []
    for kind, rx in (("TABLE", r"(?i)\bCREATE\s+TABLE\s+(?:dbo\.)?\[?(\w+)\]?"),
                     ("CONSTRAINT", r"(?i)\bCONSTRAINT\s+\[?(\w+)\]?"),
                     ("INDEX", r"(?i)\bCREATE\s+(?:UNIQUE\s+)?(?:(?:NON)?CLUSTERED\s+)?INDEX\s+\[?(\w+)\]?")):
        keys += [f"{kind}:{m}" for m in re.findall(rx, text)]
    return keys


if "-i" in args:
    path = args[args.index("-i") + 1]
    state["runs"].append({"file": os.path.basename(path), "login": os.environ.get("STORM_APP_LOGIN")})
    state["present"] = sorted(set(state["present"]) | set(objects_in(path)))
    json.dump(state, open(state_path, "w"))
    print(f"ran {os.path.basename(path)}")
    sys.exit(0)

q = args[args.index("-Q") + 1]
if "DB_ID(N'STORM_ENERGY_RTU') IS NULL" in q:
    out(1 if state.get("db_exists", True) else 0)
    sys.exit(0)
values = re.findall(r"\(N'(TABLE|CONSTRAINT|INDEX)',N'(\w+)'\)", q)
present = set(state["present"])
in_values_order = [f"{k}:{n}" for k, n in values if f"{k}:{n}" not in present]
missing = sorted(in_values_order)                       # the row query uses ORDER BY v.k, v.n
if "STRING_AGG" in q:                                   # the pre-fix query shape (no ORDER BY)
    out(",".join(in_values_order) or "NONE", state.get("rcsi", 1), state.get("tables", 8))
elif "SELECT v.k + N':' + v.n" in q:                     # one name per row
    rows = missing[:-1] if state.get("drop_last_row") else missing
    for m in rows:
        out(m)
elif "SELECT (SELECT COUNT(*) FROM (VALUES" in q:
    out(len(missing), state.get("rcsi", 1), state.get("tables", 8))
else:
    out(0)
