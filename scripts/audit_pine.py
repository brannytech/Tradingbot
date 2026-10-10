import json
import re
from pathlib import Path

root = Path(__file__).resolve().parent.parent
source = (root/"MCB_indicator.txt").read_text(encoding="utf-8")
rows = []
for i, line in enumerate(source.splitlines(), 1):
    match = re.match(r"(\w+)\s*=\s*input\.(\w+)\((.*)", line)
    if match:
        rows.append(dict(name=match[1], kind=match[2], expression=match[3], line=i))
(root/"research"/"pine-inputs.json").write_text(json.dumps(rows, indent=2))
print(json.dumps(dict(inputs=len(rows), lookahead_on_lines=[i for i,l in enumerate(source.splitlines(),1) if "lookahead_on" in l],
                      reference_parity="BLOCKED: no reference vectors")))
