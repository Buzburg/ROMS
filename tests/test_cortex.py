import os
import sys
import json
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from cortex.memory import HybridNeuralMemory
from cortex.sieve import ContextSieve
from cortex.symdex import PolyglotSymdex
from cortex.rewind import WorkspaceTimeMachine
from cortex.shield import ExecutionShield
from cortex.router import TernaryToolRouter
from cortex.runtime import (
    select_context,
    prompt_lookup,
    PrefixIndex,
    TokenBudget,
    kv_bytes,
    BinaryVector,
)
from cortex.mcp_server import CortexMCPServer, MCP_TOOLS_SCHEMA
from cortex.dashboard import generate_dashboard


class TestMojoCortex(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="cortex_test_")
        self.cortex_dir = os.path.join(self.temp_dir, ".cortex")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_memory_titans_surprise_and_recall(self):
        mem = HybridNeuralMemory(self.cortex_dir)
        r1 = mem.remember("auth_provider", "oauth2_pkce_flow", category="security")
        self.assertGreater(r1["surprise"], 0.1)
        self.assertAlmostEqual(r1["post_write_cosine"], 1.0, places=4)

        # Second write of same fact has near-zero surprise
        r2 = mem.remember("auth_provider", "oauth2_pkce_flow", category="security")
        self.assertLess(r2["surprise"], 1e-5)

        rec = mem.recall("auth_provider")
        self.assertTrue(rec["found"])
        self.assertEqual(rec["value"], "oauth2_pkce_flow")
        self.assertGreater(rec["confidence"], 0.95)

    def test_memory_deltanet_overwrite_and_pure_erase(self):
        mem = HybridNeuralMemory(self.cortex_dir)
        mem.remember("db_host", "localhost_5432")
        r_over = mem.remember("db_host", "prod_rds_cluster_01")
        self.assertAlmostEqual(r_over["post_write_cosine"], 1.0, places=4)

        rec = mem.recall("db_host")
        self.assertEqual(rec["value"], "prod_rds_cluster_01")

        # Pure Erase Gate
        er = mem.erase("db_host")
        self.assertTrue(er["erased"])
        self.assertAlmostEqual(er["residual_magnitude"], 0.0, places=5)

    def test_sieve_snapkv_log_compaction(self):
        sieve = ContextSieve(self.cortex_dir)
        lines = [f"Downloading package_dep_{i % 5} ... 100%" for i in range(300)]
        lines[149] = '  File "src/auth/jwt.py", line 88, in verify_token'
        lines[150] = "    raise ValueError('Invalid token signature')"
        lines[151] = "ValueError: Invalid token signature at src/auth/jwt.py:88"
        lines.append("Build failed with exit code 1.")
        raw_log = "\n".join(lines)

        res = sieve.compact(raw_log, max_lines=20)
        self.assertGreater(res["compression_pct"], 80.0)
        self.assertIn("src/auth/jwt.py", res["compacted_text"])
        self.assertIn("Invalid token signature", res["compacted_text"])
        self.assertIn("Build failed with exit code 1.", res["compacted_text"])

    def test_symdex_polyglot_indexing_and_lookup(self):
        py_file = os.path.join(self.temp_dir, "engine.py")
        with open(py_file, "w", encoding="utf-8") as f:
            f.write("class NeuralRouter:\n    pass\n\ndef dispatch_agent_task(task_id: int):\n    return True\n")

        mojo_file = os.path.join(self.temp_dir, "kernel.mojo")
        with open(mojo_file, "w", encoding="utf-8") as f:
            f.write("struct SimdMatrix:\n    var dim: Int\n\ndef fast_dot_product():\n    pass\n")

        sym = PolyglotSymdex(self.cortex_dir)
        idx = sym.index_workspace(self.temp_dir)
        self.assertEqual(idx["files_scanned"], 2)
        self.assertEqual(idx["total_symbols"], 4)

        lkp = sym.lookup("dispatch_agent_task")
        self.assertGreaterEqual(lkp["matches_found"], 1)
        self.assertEqual(lkp["matches"][0]["name"], "dispatch_agent_task")
        self.assertEqual(lkp["matches"][0]["line"], 4)

    def test_rewind_cow_snapshot_and_atomic_rollback(self):
        target_file = os.path.join(self.temp_dir, "config.json")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write('{"version": 1, "safe": true}')

        tm = WorkspaceTimeMachine(self.cortex_dir)
        snap = tm.snapshot("Clean state", workspace_root=self.temp_dir)
        self.assertEqual(snap["id"], "snap_001")

        # Corrupt the file
        with open(target_file, "w", encoding="utf-8") as f:
            f.write("CORRUPTED_BY_AGENT")

        rw = tm.rewind("snap_001", workspace_root=self.temp_dir)
        self.assertTrue(rw["success"])

        with open(target_file, "r", encoding="utf-8") as f:
            restored = f.read()
        self.assertEqual(restored, '{"version": 1, "safe": true}')

    def test_shield_hazard_blocking_and_loop_detection(self):
        shield = ExecutionShield(self.cortex_dir)

        # 1. Block destructive command
        hz = shield.forecast_action("sudo rm -rf /var/lib/data", goal="clean logs")
        self.assertTrue(hz["blocked"])
        self.assertIn("BLOCKED_HAZARD", hz["verdict"])

        # 2. Detect repetitive 3-turn agent loop
        shield.forecast_action("pytest tests/test_login.py", goal="run unit tests")
        shield.forecast_action("pytest tests/test_login.py", goal="run unit tests")
        loop_res = shield.forecast_action("pytest tests/test_login.py", goal="run unit tests")
        self.assertTrue(loop_res["blocked"])
        self.assertIn("BLOCKED_LOOP", loop_res["verdict"])

    def test_shield_tool_call_json_repair(self):
        shield = ExecutionShield(self.cortex_dir)
        messy = """
        Sure! I will call the search tool now:
        ```json
        {
          'name': 'cortex_symdex_lookup',
          'arguments': {
            'query': 'NeuralRouter',
            'top_k': '5',
          }
        ```
        """
        schema = {
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer"}
            }
        }
        rep = shield.repair_tool_call(messy, schema=schema)
        self.assertTrue(rep["valid"])
        self.assertEqual(rep["tool_call"]["name"], "cortex_symdex_lookup")
        self.assertEqual(rep["tool_call"]["arguments"]["top_k"], 5)
        self.assertIsInstance(rep["tool_call"]["arguments"]["top_k"], int)

    def test_router_bitnet_ternary_pruning(self):
        router = TernaryToolRouter()
        res = router.route("rewind workspace to previous snapshot", MCP_TOOLS_SCHEMA, top_k=2)
        self.assertEqual(res["selected_count"], 2)
        names = [t["name"] for t in res["selected_tools"]]
        self.assertIn("cortex_snapshot_rewind", names)

    def test_mcp_server_jsonrpc_protocol(self):
        server = CortexMCPServer(self.cortex_dir, self.temp_dir)

        # 1. initialize
        init_resp = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(init_resp["result"]["serverInfo"]["name"], "cortex")

        # 2. tools/list
        list_resp = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(len(list_resp["result"]["tools"]), 10)

        # 3. tools/call -> cortex_memory_remember
        call_resp = server.handle_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "cortex_memory_remember",
                "arguments": {"key": "api_version", "value": "v2.4"}
            }
        })
        self.assertFalse(call_resp["result"]["isError"])

        # 4. tools/call -> cortex_context_pack (ROMS)
        pack_resp = server.handle_request({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "cortex_context_pack",
                "arguments": {"costs": [50, 40, 30], "values": [100, 60, 50], "budget": 70, "required_index": 2}
            }
        })
        self.assertFalse(pack_resp["result"]["isError"])
        pack_data = json.loads(pack_resp["result"]["content"][0]["text"])
        self.assertEqual(pack_data["selected_indices"], [1, 2])

    def test_roms_knapsack_and_binary_vector(self):
        # 1. 0/1 Knapsack Context Selector with failed-attempt warning reservation
        sel = select_context([50, 40, 30], [100, 60, 50], 70, required=2)
        self.assertEqual(sel, [1, 2])

        # 2. 1-bit BinaryVector (32x compression, 48 bytes for 384 dims)
        v1 = [1.0 if i % 2 == 0 else -1.0 for i in range(384)]
        v2 = [-x for x in v1]
        b1 = BinaryVector(v1)
        b2 = BinaryVector(v2)
        self.assertEqual(b1.hamming_distance(b1), 0)
        self.assertEqual(b1.hamming_distance(b2), 384)
        self.assertAlmostEqual(b1.similarity(b1), 1.0, places=5)
        self.assertAlmostEqual(b1.similarity(b2), 0.0, places=5)

    def test_mojond_prefix_index_prompt_lookup_and_budget(self):
        # 1. PrefixIndex trie
        trie = PrefixIndex()
        trie.insert([10, 20, 30, 40], 4, 11)
        trie.insert([10, 20, 99], 3, 22)
        self.assertEqual(trie.match([10, 20, 30, 77]), (11, 3))

        # 2. Speculative prompt_lookup
        draft = prompt_lookup([1, 2, 3, 4, 5, 2, 3], window=2, limit=2)
        self.assertEqual(draft, [4, 5])

        # 3. TokenBudget & kv_bytes
        self.assertEqual(kv_bytes(32, 8, 128, 512, 2), 67108864)
        budget = TokenBudget(100)
        self.assertTrue(budget.available(60))
        budget.acquire(60)
        self.assertFalse(budget.available(50))
        budget.release(30)
        self.assertTrue(budget.available(70))

    def test_dashboard_html_generation(self):
        dash_file = os.path.join(self.temp_dir, "dash.html")
        out = generate_dashboard(self.cortex_dir, dash_file)
        self.assertTrue(os.path.exists(out))
        with open(out, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("cortex Telemetry", content)

    def test_launch_autopilot_and_html_escaping(self):
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, os.path.join(root_dir, "launch"))
        import autopilot
        import submit_directory_prs

        payloads = autopilot.build_campaign_payloads("https://github.com/Buzburg/cortex")
        html_path = autopilot.generate_control_center_html(payloads, "https://github.com/Buzburg/cortex")
        with open(html_path, "r", encoding="utf-8") as f:
            html_doc = f.read()

        # Verify <think> and <50 µs are properly HTML-escaped inside <pre> blocks
        self.assertIn("&lt;think&gt;", html_doc)
        self.assertIn("&lt;50", html_doc)
        self.assertIn("https://www.reddit.com/r/LocalLLaMA/submit?selftext=true", html_doc)

        # Verify smart README section insertion places entry inside ### Memory before ## License
        sample_readme = "# Awesome MCP\n\n### Memory\n- [existing](https://example.com)\n\n## License\nMIT\n"
        updated = submit_directory_prs.insert_entry_into_readme(sample_readme, "- [cortex](https://github.com/Buzburg/cortex)")
        self.assertLess(updated.index("cortex"), updated.index("## License"))


if __name__ == "__main__":
    unittest.main()
