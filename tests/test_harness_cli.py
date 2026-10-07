"""Verify the public CLI and MCP boundary without a model or execution service."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_cli(tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(ROOT / "roms.py"), "harness", *arguments],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
        env={**os.environ, "ROMS_DATA_DIR": str(tmp_path / "unused-data"),
             "ROMS_STATE_DIR": str(tmp_path / "unused-state"),
             "ROMS_DB_PATH": str(tmp_path / "missing.db"), "PYTHONDONTWRITEBYTECODE": "1"},
    )


def test_public_cli_from_another_working_directory(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "--request", str(ROOT / "examples/harness-request.json"))
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["schema"] == "roms.harness/v1"
    assert report["status"] == "review-required"
    assert report["approval_required"] and not report["execution_allowed"]
    assert report["backend"]["model_called"] is False
    assert not (tmp_path / "unused-data").exists()
    assert not (tmp_path / "unused-state").exists()
    assert not (tmp_path / "missing.db").exists()


def test_inline_empty_evidence_abstains_successfully(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "--goal", "Which invoice needs review?", "--options",
                     '{"review":"Review the invoice","wait":"Wait for evidence"}')
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "abstained"
    assert report["proposed_next_step"] is None
    assert report["decision"]["probabilities"] == {"review": 0.5, "wait": 0.5}


@pytest.mark.parametrize("raw", [b"[]", b"{", b'{"goal":"a","goal":"b"}',
                                 b'{"goal":NaN}', b"\xff", b" " * 32769],
                         ids=["array", "syntax", "duplicate", "nonfinite", "encoding", "oversized"])
def test_invalid_request_fails_with_no_report(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / "request.json"
    path.write_bytes(raw)
    result = run_cli(tmp_path, "--request", str(path))
    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(result.stderr)["execution_allowed"] is False
    assert not (tmp_path / "unused-data").exists()


def test_request_cannot_be_overridden_by_inline_fields(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "--request", str(ROOT / "examples/harness-request.json"), "--evidence", "override")
    assert result.returncode == 2
    assert result.stdout == ""


def test_mcp_transport_uses_configured_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastmcp import Client
    from app import server

    monkeypatch.setattr(server, "DB_PATH", tmp_path / "missing.db")
    monkeypatch.setattr(server, "SKILLS_DIR", tmp_path / "skills")
    request = (ROOT / "examples/harness-request.json").read_text(encoding="utf-8")

    async def call() -> None:
        async with Client(server.mcp) as client:
            tools = await client.list_tools()
            tool = next(tool for tool in tools if tool.name == "roms_prepare_harness")
            schema = getattr(tool, "input_schema", None)
            if schema is None:
                schema = tool.inputSchema
            assert set(schema["properties"]) == {"request_json"}
            result = await client.call_tool("roms_prepare_harness", {"request_json": request})
            report = json.loads(result.content[0].text)
            assert report["schema"] == "roms.harness/v1"
            assert report["approval_required"] and not report["execution_allowed"]
            malformed = json.dumps({**json.loads(request), "db_path": str(tmp_path / "other.db")})
            rejected = await client.call_tool("roms_prepare_harness", {"request_json": malformed}, raise_on_error=False)
            assert rejected.is_error

    asyncio.run(call())
    assert not (tmp_path / "missing.db").exists()


def test_harness_demo_exercises_real_cli() -> None:
    from scripts.demo_harness import run_demo

    result = run_demo()
    assert all(result["checks"].values())
    assert result["report"]["context"]["knowledge"]["sources"]
