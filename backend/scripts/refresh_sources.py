"""Check the planner lists for new editions by hand: python -m scripts.refresh_sources [source ...] [--promote] [--apply ID]"""
import json
import sys

from app.refresh import promote, stage
from app.refresh.sources import SOURCES

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--apply" in sys.argv:
        rid = int(sys.argv[sys.argv.index("--apply") + 1])
        out = promote.promote(rid)
        print(out["source"], out["status"], stage.summary(out["diff"]))
    elif "--promote" in sys.argv:
        print(json.dumps(promote.refresh_once(args or None), indent=1, default=str))  # the loop body: small updates go live
    else:
        for key in args or SOURCES:
            row = stage.check(key)
            print(key, row["status"], row.get("edition"), row.get("found_via"), row.get("error") or "", stage.summary(row["diff"]) if row.get("diff") else "")
