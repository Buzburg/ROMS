import os
from pathlib import Path
from app.prefrontal_cortex import (
    HybridNeuralMemory,
    ContextSieve,
    PolyglotSymdex,
    WorkspaceTimeMachine,
    ExecutionShield,
    TernaryToolRouter,
    select_context,
    prompt_lookup,
    kv_bytes,
    PrefixIndex,
    TokenBudget,
    BinaryVector,
    generate_roms_dashboard,
)


def test_titans_deltanet2_memory_overwrite_and_erase(tmp_path: Path):
    mem = HybridNeuralMemory(state_dir=str(tmp_path / "prefrontal"))
    r1 = mem.remember("auth_flow", "jwt_hs256")
    assert r1["post_write_cosine"] > 0.99

    r2 = mem.remember("auth_flow", "oauth2_pkce_strict")
    assert r2["post_write_cosine"] > 0.99

    rec = mem.recall("auth_flow")
    assert rec["found"] is True
    assert rec["value"] == "oauth2_pkce_strict"

    er = mem.erase("auth_flow")
    assert er["erased"] is True
    assert er["residual_magnitude"] < 1e-4


def test_snapkv_context_sieve_compaction(tmp_path: Path):
    sieve = ContextSieve(state_dir=str(tmp_path / "prefrontal"))
    lines = ["GET /health 200 OK" for _ in range(200)]
    lines[85] = '  File "src/auth.py", line 42, in verify_token'
    lines[86] = "AssertionError: Fatal token signature mismatch"
    lines.append("FAILED (errors=1)")
    res = sieve.compact("\n".join(lines), max_lines=15)
    assert res["compression_pct"] > 75.0
    assert "src/auth.py" in res["compacted_text"]
    assert "AssertionError" in res["compacted_text"]


def test_polyglot_symdex_and_cow_time_machine(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    sample = ws / "engine.py"
    sample.write_text("class NeuralCartridge:\n    def execute_step(self):\n        return 42\n", encoding="utf-8")

    state_dir = str(tmp_path / "prefrontal")
    sym = PolyglotSymdex(state_dir=state_dir)
    idx = sym.index_workspace(str(ws))
    assert idx["total_symbols"] >= 2
    hit = sym.lookup("NeuralCartridge", workspace_root=str(ws))
    assert hit["matches_found"] >= 1
    assert hit["matches"][0]["name"] == "NeuralCartridge"

    tm = WorkspaceTimeMachine(state_dir=state_dir)
    snap = tm.snapshot("Before risky edit", workspace_root=str(ws))
    sample.write_text("BROKEN WORKSPACE CONTENT", encoding="utf-8")
    rew = tm.rewind(snap["id"], workspace_root=str(ws))
    assert rew["success"] is True
    assert "class NeuralCartridge:" in sample.read_text(encoding="utf-8")


def test_execution_shield_and_json_repair(tmp_path: Path):
    shield = ExecutionShield(state_dir=str(tmp_path / "prefrontal"))
    bad = shield.forecast_action("rm -rf /var/lib/postgresql", goal="clean logs")
    assert bad["blocked"] is True
    assert "BLOCKED_HAZARD" in bad["verdict"]

    repaired = shield.repair_tool_call(
        "```json\n{'name': 'lookup', 'arguments': {'query': 'main', 'top_k': '5',}}\n```",
        schema={"properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}}},
    )
    assert repaired["valid"] is True
    assert repaired["tool_call"]["arguments"]["top_k"] == 5


def test_ternary_router_and_runtime_primitives(tmp_path: Path):
    router = TernaryToolRouter()
    tools = [
        {"name": "roms_snapshot_rewind", "description": "rewind broken workspace files to snapshot"},
        {"name": "send_email", "description": "send marketing newsletter email"},
        {"name": "weather_forecast", "description": "check rain and temperature"},
        {"name": "roms_sieve_compact", "description": "compact verbose terminal logs"},
    ]
    routed = router.route("rewind broken workspace files to snapshot", tools, top_k=1)
    assert routed["selected_tools"][0]["name"] == "roms_snapshot_rewind"
    assert routed["token_reduction_pct"] == 75.0

    picked = select_context([50, 40, 30], [100, 60, 50], budget=70, required=2)
    assert 2 in picked

    draft = prompt_lookup([1, 2, 3, 4, 5, 2, 3], window=2, limit=2)
    assert draft == [4, 5]

    trie = PrefixIndex()
    trie.insert([10, 20, 30, 40], 4, slot=7)
    slot, count = trie.match([10, 20, 30, 99])
    assert slot == 7 and count == 3

    tb = TokenBudget(100)
    tb.acquire(60)
    assert tb.available(40) is True
    tb.release(60)

    bv1 = BinaryVector([1.0, -1.0, 1.0, -1.0])
    bv2 = BinaryVector([1.0, -1.0, 1.0, -1.0])
    assert bv1.similarity(bv2) == 1.0
    assert kv_bytes(32, 32, 128, 2048, 2) > 0

    dash_file = tmp_path / "roms_dashboard.html"
    out = generate_roms_dashboard(state_dir=str(tmp_path / "prefrontal"), output_path=str(dash_file))
    assert os.path.exists(out)
    assert "ROMS harness telemetry" in dash_file.read_text(encoding="utf-8")
