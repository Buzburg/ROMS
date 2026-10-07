"""A dependency-free first run must prove its checks, including failures."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import demo_first_run as demo


SCRIPT = Path(demo.__file__).resolve()


class FirstRunDemoTests(unittest.TestCase):
    def test_no_install_command_runs_outside_checkout_and_preserves_caller_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            caller = Path(temporary)
            sentinel = caller / "invoice.py"
            sentinel.write_bytes(b"User work must remain untouched.\n")
            data = caller / "existing-roms-data"
            environment = {**os.environ, "ROMS_DATA_DIR": str(data)}
            completed = subprocess.run(
                [sys.executable, "-I", "-S", "-B", str(SCRIPT), "--json"],
                cwd=caller, env=environment, capture_output=True, text=True,
                encoding="utf-8", timeout=30, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            report = json.loads(completed.stdout)
            self.assertEqual(report["status"], "passed")
            self.assertTrue(all(report["checks"].values()))
            self.assertEqual(report["fixture_exit_codes"], [0, 1, 0])
            self.assertTrue(report["temporary_files_removed"])
            self.assertIn(demo.FAILURE, report["log"]["full_failed_log"])
            self.assertIn(demo.FAILURE, report["log"]["compacted_log"])
            self.assertEqual(report["log"]["original_lines"], len(report["log"]["full_failed_log"].splitlines()))
            self.assertLessEqual(report["log"]["selected_source_lines"], demo.LINE_BUDGET)
            self.assertLess(report["log"]["compacted_characters"], report["log"]["original_characters"])
            hashes = report["source_sha256"]
            self.assertEqual(hashes["original"], hashes["restored"])
            self.assertNotEqual(hashes["original"], hashes["broken"])
            self.assertEqual(sentinel.read_bytes(), b"User work must remain untouched.\n")
            self.assertFalse(data.exists())
            self.assertEqual(list(caller.iterdir()), [sentinel])

    def test_dropped_diagnostic_fails_and_removes_temporary_workspace(self) -> None:
        touched: list[Path] = []
        real_run = demo._run_fixture

        def run(source: Path) -> subprocess.CompletedProcess[str]:
            touched.append(source.parent.parent)
            return real_run(source)

        with patch.object(demo, "_run_fixture", side_effect=run), patch.object(
            demo.ContextSieve, "compact", return_value={"compacted_text": "Everything is fine"}
        ):
            with self.assertRaisesRegex(demo.DemoFailure, "lost the expected failure"):
                demo.run_demo()
        self.assertTrue(touched)
        self.assertTrue(all(not path.exists() for path in touched))

    def test_false_success_from_restore_is_not_trusted(self) -> None:
        with patch.object(demo.WorkspaceTimeMachine, "rewind", return_value={
            "success": True, "files_restored": 1,
        }):
            with self.assertRaisesRegex(demo.DemoFailure, "differs from the original bytes"):
                demo.run_demo()

    def test_restored_file_must_also_pass_the_real_check(self) -> None:
        real_run = demo._run_fixture
        calls = 0

        def run(source: Path) -> subprocess.CompletedProcess[str]:
            nonlocal calls
            calls += 1
            if calls == 3:
                return subprocess.CompletedProcess([], 1, "Check failed after restore")
            return real_run(source)

        with patch.object(demo, "_run_fixture", side_effect=run):
            with self.assertRaisesRegex(demo.DemoFailure, "restored fixture check did not pass"):
                demo.run_demo()

    def test_failed_check_has_nonzero_exit_and_no_success_report(self) -> None:
        output = io.StringIO()
        with patch.object(demo, "run_demo", side_effect=demo.DemoFailure("missing evidence")):
            with redirect_stdout(output):
                code = demo.main(["--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue()), {
            "schema_version": 1, "status": "failed", "error": "missing evidence",
        })


if __name__ == "__main__":
    unittest.main()
