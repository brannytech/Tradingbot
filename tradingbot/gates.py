"""Evidence records are immutable through the web API. No manual PASS controls."""
import hashlib
import json
from pathlib import Path
from typing import Any

TITLES = ["Repository Discovery", "Architecture and Security", "Bybit Connectivity",
          "Strategy Research", "Individual Strategy Agents", "Statistical Validation",
          "Consensus Engine", "Risk and Execution Safety", "Demo Trading",
          "Dashboard Readiness", "Reliability and Security", "Pre-Live Readiness", "Live Activation"]
# Offline strategy/consensus work is independent of exchange ingestion and demo.
DEPENDENCIES: dict[int,list[int]] = {0: [], 1: [0], 2: [1], 3: [0], 4: [1, 3], 5: [4, 2],
                6: [4], 7: [1, 6], 8: [2, 5, 6, 7], 9: [1], 10: [7, 8, 9], 11: list(range(12))[:11], 12: [11]}


def source_hash():
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parent.parent
    for base in ("tradingbot", "tests", "scripts", "research", ".github"):
        for path in sorted((root/base).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".html", ".md", ".json", ".mjs", ".yml"):
                digest.update(str(path.relative_to(root)).encode())
                digest.update(path.read_bytes())
    for name in ("pyproject.toml","README.md","MCB_indicator.txt","package.json","playwright.config.mjs"):
        path=root/name
        if path.exists():
            digest.update(name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def gate_records(path="reports/gates.json"):
    p = Path(path)
    rows: list[dict[str,Any]] = json.loads(p.read_text()) if p.exists() else []
    by_id = {r["id"]: r for r in rows}
    result: list[dict[str,Any]] = []
    current_hash=source_hash()
    for i, title in enumerate(TITLES):
        row: dict[str,Any] = by_id.get(i, dict(id=i, title=title, status="LOCKED" if i == 12 else "NOT STARTED",
                               evidence=[], known_issues=["Verification not yet executed"]))
        row = dict(row)
        if row.get("status") == "PASS" and row.get("source_hash") != current_hash:
            row["status"] = "BLOCKED"
            row["known_issues"] = ["Source changed since verification; rerun scripts/verify.py"]
        result.append(row)
    for row in result:
        prerequisites = DEPENDENCIES[row["id"]]
        row["dependencies"] = prerequisites
        row["progression_allowed"] = row["status"] == "PASS" and all(result[d]["status"] == "PASS" for d in prerequisites)
        if row["status"] == "PASS" and not row["progression_allowed"]:
            row["status"] = "BLOCKED"
    return result
