"""
Unified Command-Line Interface for cortex.
"""

import os
import sys
import json
import argparse
from .memory import HybridNeuralMemory
from .sieve import ContextSieve
from .symdex import PolyglotSymdex
from .rewind import WorkspaceTimeMachine
from .shield import ExecutionShield
from .router import TernaryToolRouter
from .runtime import select_context, prompt_lookup
from .mcp_server import CortexMCPServer, MCP_TOOLS_SCHEMA
from .dashboard import generate_dashboard


def run_cli():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        prog="cortex",
        description="cortex: Universal Prefrontal Cortex, Associative Memory, & Safety Harness for AI Agents"
    )
    subparsers = parser.add_subparsers(dest="command")

    # 1. Remember
    rem_p = subparsers.add_parser("remember", help="Store or overwrite fact in Titans + DeltaNet-2 neural memory")
    rem_p.add_argument("--key", required=True)
    rem_p.add_argument("--value", required=True)
    rem_p.add_argument("--category", default="architecture")

    # 2. Recall
    rec_p = subparsers.add_parser("recall", help="Recall fact from neural memory")
    rec_p.add_argument("--query", required=True)

    # 3. Erase
    era_p = subparsers.add_parser("erase", help="Surgically erase key from neural memory")
    era_p.add_argument("--key", required=True)

    # 4. Index
    idx_p = subparsers.add_parser("index", help="Build zero-DB polyglot codebase symbol index")
    idx_p.add_argument("--path", default=".")

    # 5. Lookup
    lkp_p = subparsers.add_parser("lookup", help="Sub-millisecond codebase symbol lookup")
    lkp_p.add_argument("--query", required=True)

    # 6. Sieve
    siv_p = subparsers.add_parser("sieve", help="Compact verbose terminal logs via SnapKV observation windows")
    siv_p.add_argument("--file", help="Path to log file")
    siv_p.add_argument("--text", help="Raw text to compact")
    siv_p.add_argument("--max-lines", type=int, default=30)

    # 7. Snapshot
    snp_p = subparsers.add_parser("snapshot", help="Take deduplicated copy-on-write workspace snapshot")
    snp_p.add_argument("--label", default="Manual checkpoint")

    # 8. Rewind
    rwd_p = subparsers.add_parser("rewind", help="Atomically rewind workspace to snapshot")
    rwd_p.add_argument("--id", required=True)

    # 9. Forecast
    fc_p = subparsers.add_parser("forecast", help="Run pre-simulation forecast, loop detector & hazard gate")
    fc_p.add_argument("--action", required=True)
    fc_p.add_argument("--goal", default=None)

    # 10. Repair
    rep_p = subparsers.add_parser("repair", help="Repair malformed local LLM tool-call JSON")
    rep_p.add_argument("--raw", required=True)

    # 11. Route
    rt_p = subparsers.add_parser("route", help="Route query across MCP tools via BitNet b1.58 ternary GEMV")
    rt_p.add_argument("--query", required=True)
    rt_p.add_argument("--top-k", type=int, default=3)

    # 12. Pack (ROMS 0/1 Knapsack Context Selector)
    pck_p = subparsers.add_parser("pack", help="Optimal 0/1 knapsack context packing with warning reservation (ROMS)")
    pck_p.add_argument("--costs", required=True, help="Comma-separated chunk costs")
    pck_p.add_argument("--values", required=True, help="Comma-separated chunk relevance values")
    pck_p.add_argument("--budget", type=int, required=True, help="Token/character budget")
    pck_p.add_argument("--required", type=int, default=-1, help="Mandatory failed-attempt warning index")

    # 13. Draft (mojond Speculative Prompt Lookup)
    drf_p = subparsers.add_parser("draft", help="Parameter-free prompt-lookup speculative token drafting (mojond)")
    drf_p.add_argument("--tokens", required=True, help="Comma-separated token IDs")
    drf_p.add_argument("--ngram", type=int, default=4)
    drf_p.add_argument("--budget", type=int, default=4)

    # 14. Dashboard
    dash_p = subparsers.add_parser("dashboard", help="Generate standalone dark-mode HTML observability dashboard")
    dash_p.add_argument("--out", default="cortex_dashboard.html")

    # 15. MCP Server
    subparsers.add_parser("mcp", help="Start JSON-RPC 2.0 Model Context Protocol (MCP) server on stdio")

    # 16. Status
    subparsers.add_parser("status", help="Display complete Cortex telemetry & subsystem health")

    args = parser.parse_args()

    if args.command == "remember":
        res = HybridNeuralMemory().remember(args.key, args.value, category=args.category)
        print(f"[+] Memorized '{res['key']}' -> '{res['value']}' in {res['latency_us']:.1f} us")
        print(f"    Surprise: {res['surprise']:.4f} | Post-Write Cosine: {res['post_write_cosine']:.4f} | Norm: {res['frobenius_norm']:.4f}")

    elif args.command == "recall":
        res = HybridNeuralMemory().recall(args.query)
        if res["found"]:
            print(f"[+] Recalled [{res['category']}] '{res['key']}' -> '{res['value']}' (Confidence: {res['confidence']:.4f}, {res['latency_us']:.1f} us)")
        else:
            print(f"[-] No memory match found for '{args.query}'")

    elif args.command == "erase":
        res = HybridNeuralMemory().erase(args.key)
        print(f"[+] Erased '{args.key}' via DeltaNet-2 Gate | Residual Norm: {res['residual_magnitude']:.6f} ({res['latency_us']:.1f} us)")

    elif args.command == "index":
        res = PolyglotSymdex().index_workspace(args.path)
        print(f"[+] Indexed {res['total_symbols']} symbols across {res['files_scanned']} files in {res['latency_ms']:.2f} ms")

    elif args.command == "lookup":
        res = PolyglotSymdex().lookup(args.query)
        print(f"[+] Found {res['matches_found']} symbol matches in {res['latency_us']:.1f} us:")
        for m in res["matches"]:
            print(f"    - [{m['kind']}] {m['name']} ({m['file']}:{m['line']}) -> {m['signature']}")

    elif args.command == "sieve":
        raw = args.text or ""
        if args.file and os.path.exists(args.file):
            with open(args.file, "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read()
        res = ContextSieve().compact(raw, max_lines=args.max_lines)
        print(res["compacted_text"])
        print(f"\n[+] Compacted {res['original_lines']} -> {res['retained_lines']} lines ({res['compression_pct']}% reduction, {res['tokens_saved']} tokens saved in {res['latency_ms']:.2f} ms)")

    elif args.command == "snapshot":
        res = WorkspaceTimeMachine().snapshot(args.label)
        print(f"[+] Created CoW Snapshot '{res['id']}' ({res['files_tracked']} files tracked in {res['latency_ms']:.2f} ms)")

    elif args.command == "rewind":
        res = WorkspaceTimeMachine().rewind(args.id)
        if res["success"]:
            print(f"[+] Rewound workspace to '{res['snapshot_id']}' ({res['files_restored']} files restored in {res['latency_ms']:.2f} ms)")
        else:
            print(f"[-] Error: {res['error']}")

    elif args.command == "forecast":
        res = ExecutionShield().forecast_action(args.action, goal=args.goal)
        print(f"=== Pre-Simulation Shield Forecast ({res['latency_us']:.1f} us) ===")
        print(f"  Action:         {res['action']}")
        print(f"  Verdict:        {res['verdict']}")
        print(f"  P(Success):     {res['p_success']:.4f}")
        print(f"  Goal Alignment: {res['goal_alignment']:.4f}")
        print(f"  Hazard Score:   {res['hazard_score']:.4f}")

    elif args.command == "repair":
        res = ExecutionShield().repair_tool_call(args.raw)
        if res["valid"]:
            print(f"[+] Repaired Tool Call in {res['latency_us']:.1f} us:")
            print(json.dumps(res["tool_call"], indent=2))
        else:
            print(f"[-] Repair failed: {res['error']}")

    elif args.command == "route":
        res = TernaryToolRouter().route(args.query, MCP_TOOLS_SCHEMA, top_k=args.top_k)
        print(f"[+] BitNet b1.58 Ternary Router selected {res['selected_count']}/{res['total_tools']} tools ({res['token_reduction_pct']}% schema pruned in {res['latency_us']:.1f} us):")
        for t in res["selected_tools"]:
            print(f"    - {t['name']}: {t['description']}")

    elif args.command == "pack":
        costs = [int(x.strip()) for x in args.costs.split(",") if x.strip()]
        values = [int(x.strip()) for x in args.values.split(",") if x.strip()]
        sel = select_context(costs, values, args.budget, args.required)
        print(f"[+] ROMS 0/1 Knapsack Context Selector chose indices {sel} (cost={sum(costs[i] for i in sel)}/{args.budget}, value={sum(values[i] for i in sel)})")

    elif args.command == "draft":
        tokens = [int(x.strip()) for x in args.tokens.split(",") if x.strip()]
        drafted = prompt_lookup(tokens, args.ngram, args.budget)
        print(f"[+] mojond Speculative Prompt Lookup drafted {len(drafted)} tokens: {drafted}")

    elif args.command == "dashboard":
        out = generate_dashboard(output_path=args.out)
        print(f"[+] Generated interactive HTML dashboard at: {out}")

    elif args.command == "mcp":
        CortexMCPServer().serve_stdio()

    elif args.command == "status":
        mem = HybridNeuralMemory().stats()
        siv = ContextSieve().stats()
        sym = PolyglotSymdex().stats()
        snaps = WorkspaceTimeMachine().list_snapshots()
        shd = ExecutionShield().stats()
        print("=" * 65)
        print("               cortex System Telemetry")
        print("=" * 65)
        print(f"  Neural Memory Entries: {len(mem.get('entries', {}))} (||M||_F = {mem.get('frobenius_norm', 0.0):.3f})")
        print(f"  Tokens Saved by Sieve: {siv.get('saved_tokens', 0):,} tokens across {siv.get('compactions', 0)} compactions")
        print(f"  Indexed Code Symbols:  {sym.get('total_symbols', 0):,} symbols ({sym.get('files_scanned', 0)} files)")
        print(f"  Workspace Snapshots:   {len(snaps)} deduplicated CoW checkpoints")
        print(f"  Shield Intercepts:     {shd.get('intercepts', 0)} hazards/loops blocked | {shd.get('repairs', 0)} tool calls repaired")
        print("=" * 65)

    else:
        parser.print_help()
