"""Exercise the portable CLI against a temporary, explicitly synthetic OKF index."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run_demo() -> dict:
    with tempfile.TemporaryDirectory(prefix="roms-harness-") as directory:
        root = Path(directory)
        database = root / "knowledge.db"
        skills = root / "skills"
        skills.mkdir()
        skill_text = "# Invoice review\nInspect the failing check, calculate the charge, and propose a change for review.\n"
        (skills / "invoice-review.md").write_bytes(skill_text.encode("utf-8"))
        document = "Invoice calculation policy: include the delivery charge when reviewing the failed invoice check."
        checksum = hashlib.sha256(document.encode()).hexdigest()
        connection = sqlite3.connect(database)
        try:
            connection.execute("CREATE VIRTUAL TABLE fts_chunks USING fts5(chunk_id UNINDEXED, doc_id UNINDEXED, content)")
            connection.execute("CREATE TABLE okf_registry(doc_id TEXT PRIMARY KEY, title TEXT, checksum TEXT)")
            connection.execute("INSERT INTO fts_chunks VALUES (1, ?, ?)", ("demo-invoice-policy", document))
            connection.execute("INSERT INTO okf_registry VALUES (?, ?, ?)", ("demo-invoice-policy", "Synthetic invoice policy", checksum))
            connection.commit()
        finally:
            connection.close()
        database_before = database.read_bytes()
        request = json.loads((ROOT / "examples/harness-request.json").read_text(encoding="utf-8"))
        request["skills"] = ["invoice-review"]
        request_file = root / "request.json"
        request_file.write_text(json.dumps(request), encoding="utf-8")
        environment = {**os.environ, "ROMS_DATA_DIR": str(root / "unused-data"),
                       "ROMS_STATE_DIR": str(root / "unused-state"),
                       "PYTHONDONTWRITEBYTECODE": "1", "HF_HUB_OFFLINE": "1"}
        process = subprocess.run(
            [sys.executable, "-B", str(ROOT / "roms.py"), "harness", "--request", str(request_file),
             "--db", str(database), "--skills-dir", str(skills)],
            cwd=ROOT, env=environment, text=True, capture_output=True, timeout=30, check=False,
        )
        if process.returncode:
            raise RuntimeError("Harness CLI failed: " + process.stderr.strip())
        report = json.loads(process.stdout)
        sources = report["context"]["knowledge"]["sources"]
        checks = {
            "indexed_knowledge_retrieved": bool(sources) and sources[0]["index_checksum"] == checksum,
            "selected_skill_loaded": report["context"]["skills"][0]["content"] == skill_text,
            "review_proposed": report["status"] == "review-required" and report["decision"]["choice"] == "review",
            "approval_boundary_preserved": report["approval_required"] and not report["execution_allowed"],
            "index_unchanged": database.read_bytes() == database_before,
            "decision_state_not_saved": not (root / "unused-state").exists(),
            "default_data_not_created": not (root / "unused-data").exists(),
        }
        if not all(checks.values()):
            raise RuntimeError("Harness demo checks failed: " + json.dumps(checks))
        return {"scope": "Synthetic OKF/FTS fixture; real ROMS retrieval, Decision Maker and CLI. No model or execution.",
                "checks": checks, "report": report}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print the complete real report")
    args = parser.parse_args()
    try:
        result = run_demo()
    except (OSError, ValueError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as error:
        print("Harness demo failed: " + str(error), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))
    else:
        print(result["scope"])
        for name, passed in result["checks"].items():
            print(f"{'PASS' if passed else 'FAIL'}: {name.replace('_', ' ')}")
        print("Proposal: " + result["report"]["proposed_next_step"])
        print("Temporary demo files removed. Nothing was executed or approved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
