"""Run ROMS's real log, symbol, and recovery tools on a disposable fixture."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.prefrontal_cortex import ContextSieve, PolyglotSymdex, WorkspaceTimeMachine


FIXTURE = '''def invoice_total_cents(items, delivery):
    return sum(items) + delivery


if __name__ == "__main__":
    for number in range(200):
        print(f"INFO invoice item scan {number}: ok")
    actual = invoice_total_cents([1250, 250], 50)
    if actual != 1550:
        raise AssertionError(f"invoice total: expected 1550 cents; got {actual}")
    print("PASS: invoice total is 1550 cents")
'''
FAILURE = "AssertionError: invoice total: expected 1550 cents; got 1500"
SUCCESS = "PASS: invoice total is 1550 cents"
LINE_BUDGET = 12


class DemoFailure(RuntimeError):
    """An observed result did not satisfy the demonstration's checks."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DemoFailure(message)


def _run_fixture(source: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-u", str(source)],
        cwd=source.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )


def run_demo() -> dict[str, Any]:
    """Create, check, and remove an isolated workspace; accept no user paths."""
    with tempfile.TemporaryDirectory(prefix="roms-first-run-") as temporary:
        base = Path(temporary)
        workspace = base / "fixture"
        workspace.mkdir()
        source = workspace / "invoice.py"
        original = FIXTURE.encode("utf-8")
        source.write_bytes(original)
        state = str(base / "state")

        baseline = _run_fixture(source)
        _require(baseline.returncode == 0 and SUCCESS in baseline.stdout,
                 "The original fixture check did not pass.")
        recovery = WorkspaceTimeMachine(state_dir=state)
        snapshot = recovery.snapshot("Before the demonstration's known bad edit", str(workspace))
        _require(snapshot["files_tracked"] == 1, "The snapshot did not contain the fixture.")

        broken = original.replace(b"sum(items) + delivery", b"sum(items)")
        source.write_bytes(broken)
        failed = _run_fixture(source)
        _require(failed.returncode != 0 and FAILURE in failed.stdout,
                 "The introduced bug did not produce the expected real failure.")

        compacted = ContextSieve(state_dir=state).compact(failed.stdout, max_lines=LINE_BUDGET)
        _require(FAILURE in compacted["compacted_text"] and "invoice.py" in compacted["compacted_text"],
                 "The compacted log lost the expected failure or its file pointer.")
        _require(compacted["retained_lines"] <= LINE_BUDGET,
                 "The sieve exceeded the selected source-line budget.")
        _require(len(compacted["compacted_text"]) < len(failed.stdout),
                 "The compacted log was not smaller than the original.")

        symbols = PolyglotSymdex(state_dir=state)
        symbols.index_workspace(str(workspace))
        lookup = symbols.lookup("invoice_total_cents", workspace_root=str(workspace))
        matches = [match for match in lookup["matches"]
                   if match["file"] == "invoice.py" and match["name"] == "invoice_total_cents"]
        _require(len(matches) == 1 and matches[0]["line"] == 1,
                 "The symbol lookup did not locate the fixture's invoice function.")

        restored = recovery.rewind(snapshot["id"], str(workspace))
        _require(restored["success"] and restored["files_restored"] == 1,
                 "The snapshot restore did not report one restored file.")
        restored_bytes = source.read_bytes()
        _require(restored_bytes == original, "The restored fixture differs from the original bytes.")
        rerun = _run_fixture(source)
        _require(rerun.returncode == 0 and SUCCESS in rerun.stdout,
                 "The restored fixture check did not pass.")

        report: dict[str, Any] = {
            "schema_version": 1,
            "status": "passed",
            "scenario": "Recover a known invoice-calculation bug in a temporary fixture",
            "checks": {
                "baseline_passed": True,
                "introduced_bug_failed": True,
                "failure_and_file_pointer_preserved": True,
                "symbol_located": True,
                "restored_bytes_match": True,
                "restored_check_passed": True,
            },
            "log": {
                "original_lines": len(failed.stdout.splitlines()),
                "selected_source_lines": compacted["retained_lines"],
                "selected_source_line_budget": LINE_BUDGET,
                "displayed_lines_including_omission_markers": len(compacted["compacted_text"].splitlines()),
                "original_characters": len(failed.stdout),
                "compacted_characters": len(compacted["compacted_text"]),
                "full_failed_log": failed.stdout,
                "compacted_log": compacted["compacted_text"],
            },
            "symbol": matches[0],
            "source_sha256": {
                "original": hashlib.sha256(original).hexdigest(),
                "broken": hashlib.sha256(broken).hexdigest(),
                "restored": hashlib.sha256(restored_bytes).hexdigest(),
            },
            "fixture_exit_codes": [baseline.returncode, failed.returncode, rerun.returncode],
            "scope": "Existing Python tools, a generated log, and a known edit; no model or GPU is used.",
        }
    report["temporary_files_removed"] = not base.exists()
    _require(report["temporary_files_removed"], "Temporary fixture cleanup did not complete.")
    return report


def _summary(report: dict[str, Any]) -> str:
    log = report["log"]
    symbol = report["symbol"]
    return "\n".join([
        "ROMS: find the failure, locate the code, restore the working file.",
        "A disposable invoice example. No model, downloads, or project files required.",
        "",
        "PASS  Original invoice check: 1550 cents.",
        "PASS  Known bad edit detected: 1500 cents instead of 1550.",
        f"PASS  Log: {log['original_lines']} lines -> {log['selected_source_lines']} selected source lines "
        f"({log['displayed_lines_including_omission_markers']} including omission markers).",
        "      Kept the actual exception and invoice.py file pointer.",
        f"PASS  Located {symbol['name']} at {symbol['file']}:{symbol['line']}.",
        "PASS  Restored original bytes; the invoice check passes again.",
        "PASS  Temporary files removed.",
        "",
        "This verifies a fixture recovery, not an autonomous repair or model benchmark.",
        "Use --json for the complete failed log, compacted log, and source hashes.",
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print the checks and complete captured failure log as JSON")
    args = parser.parse_args(argv)
    try:
        report = run_demo()
    except (DemoFailure, OSError, subprocess.SubprocessError, KeyError, ValueError) as error:
        if args.json:
            print(json.dumps({"schema_version": 1, "status": "failed", "error": str(error)}))
        else:
            print(f"ROMS demo failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2) if args.json else _summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
