r"""Comprehensive verification suite for integrations ported from D:\Buzburg Files\Harness Repos.

Tests:
1. 16,384-bit Binary Spatter Code (BSC) Vector Symbolic Architecture (VSA)
2. Hopfield associative memory bank
3. Telegraphic Symbolic Language (TSL) streaming FSM parser
4. Adaptive Speculative Decoding controller
5. Agency Agents 280-role catalog registry (279 standard + 1 integration)
6. Omarchy OS desktop packaging files
"""

from pathlib import Path
import pytest

from app.vsa_tsl_engine import (
    HypervectorBSC,
    HolographicMemoryBank,
    TSLStreamParser,
    build_tsl_prompt,
    AdaptiveSpeculativeController,
)
from app.role_registry import RoleRegistry, role_registry


def test_hypervector_bsc_vsa_properties():
    # Deterministic generation
    hv_a = HypervectorBSC.from_seed("Omarchy_OS")
    hv_b = HypervectorBSC.from_seed("RWKV7_Engine")
    hv_c = HypervectorBSC.from_seed("Omarchy_OS")

    # Identity
    assert hv_a.hamming_distance(hv_c) == 0
    assert pytest.approx(hv_a.cosine_similarity(hv_c), 0.001) == 1.0

    # Pseudo-orthogonality (~8192 bits differ out of 16384)
    dist_ab = hv_a.hamming_distance(hv_b)
    assert 7000 < dist_ab < 9500
    assert abs(hv_a.cosine_similarity(hv_b)) < 0.2

    # XOR Binding self-inverse: (A ^ B) ^ B == A
    bound = hv_a.bind(hv_b)
    recovered = bound.bind(hv_b)
    assert recovered.hamming_distance(hv_a) == 0
    assert pytest.approx(recovered.cosine_similarity(hv_a), 0.001) == 1.0

    # Permutation produces orthogonal vector
    permuted = hv_a.permute(shift=1)
    assert permuted.hamming_distance(hv_a) > 6000


def test_holographic_memory_bank_hopfield_cleanup():
    bank = HolographicMemoryBank(threshold=0.15)
    hv_agent = bank.insert_symbol("Code_Reviewer")
    hv_task = bank.insert_symbol("Verify_AST")

    # Query with exact key
    nearest, sim = bank.find_nearest(hv_agent)
    assert nearest == "Code_Reviewer"
    assert pytest.approx(sim, 0.001) == 1.0

    # Query with bound composite (should not match un-bound atom above threshold)
    composite = hv_agent.bind(hv_task)
    nearest_bound, _ = bank.find_nearest(composite)
    assert nearest_bound is None

    # Unbind and retrieve
    unbound = composite.bind(hv_task)
    recovered_key, rec_sim = bank.find_nearest(unbound)
    assert recovered_key == "Code_Reviewer"
    assert rec_sim > 0.99


def test_tsl_stream_parser():
    parser = TSLStreamParser()

    # Feed fragmented tokens across multiple chunks
    t1, trips1 = parser.feed('[OUT:"Hello, ')
    assert t1 == "Hello, "
    assert len(trips1) == 0

    t2, trips2 = parser.feed('Omarchy World!"][ADD:(Agent')
    assert t2 == "Omarchy World!"
    assert len(trips2) == 0

    t3, trips3 = parser.feed(' uses MSGL)]')
    assert t3 == ""
    assert len(trips3) == 1
    assert trips3[0].subject == "Agent"
    assert trips3[0].relation == "uses"
    assert trips3[0].object == "MSGL"

    assert parser.output_text == "Hello, Omarchy World!"
    assert len(parser.bound_triples) == 1


def test_build_tsl_prompt():
    prompt = build_tsl_prompt(
        role="Systems_Architect",
        repo_ast_context="def route(): pass",
        mem_triples=["Omarchy runs Strix_Halo"],
        goal="Optimize speculative decoding",
    )
    assert "[ROLE:Systems_Architect]" in prompt
    assert "[REPO_AST:\ndef route(): pass]" in prompt
    assert "[MEM:(Omarchy runs Strix_Halo)]" in prompt
    assert '[GOAL:"Optimize speculative decoding"]' in prompt
    assert "Respond strictly in TSL format" in prompt


def test_adaptive_speculative_controller():
    controller = AdaptiveSpeculativeController(min_draft_tokens=1, max_draft_tokens=8, target_acceptance_rate=0.6)
    initial_k = controller.current_draft_tokens

    # High acceptance rate should increase K
    new_k = controller.record_step(drafted=4, accepted=4)  # 100% acceptance
    assert new_k >= initial_k

    # Low acceptance rate should decrease K
    new_k2 = controller.record_step(drafted=8, accepted=1)  # 12.5% acceptance
    assert new_k2 < new_k
    assert controller.overall_acceptance_rate > 0.0


def test_agency_roles_registry():
    # Verify loaded catalog count (279 standard roles + 1 integration variant = 280)
    assert len(role_registry.roles) == 280
    categories = role_registry.list_categories()
    assert "engineering" in categories
    assert "design" in categories

    # Query specific role
    reviewer = role_registry.get_role("engineering/engineering-code-reviewer")
    assert reviewer is not None
    assert reviewer.name == "Code Reviewer"
    assert "review" in reviewer.description.lower()

    # Search roles
    results = role_registry.search_roles("architect", limit=5)
    assert len(results) > 0
    assert any("architect" in r.name.lower() for r in results)

    # Prompt formatting
    formatted = role_registry.format_agent_prompt(
        "engineering/engineering-code-reviewer",
        custom_instructions="Review this pull request for thread safety.",
    )
    assert "Code Reviewer" in formatted
    assert "thread safety" in formatted


def test_omarchy_packaging_files():
    base_dir = Path(__file__).resolve().parent.parent
    desktop_file = base_dir / "packaging" / "omarchy.desktop"
    menu_file = base_dir / "packaging" / "omarchy-menu"
    service_file = base_dir / "packaging" / "omarchy-model@.service"
    install_script = base_dir / "scripts" / "install-omarchy.sh"

    assert desktop_file.exists()
    assert menu_file.exists()
    assert service_file.exists()
    assert install_script.exists()

    desktop_content = desktop_file.read_text(encoding="utf-8")
    assert "Name=ROMS\n" in desktop_content
    assert "by Buzburg" in desktop_content
    assert "Exec=omarchy-menu" in desktop_content
