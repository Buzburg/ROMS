"""Tool capability hints and explicit plugin selection; hints are not authorization."""
import os
from pathlib import Path
import re

# Read operations can initialize application caches/indexes, but do not author user content.
READ_TOOLS = frozenset("""
draft_task_skill prepare_knowledge_brief
search_knowledge_skills get_knowledge_skill prepare_task_skill finalize_task_skill
search_saved_task_skills get_saved_task_skill
roms_prepare_harness search_knowledge_base search_grounded_context
knowledge_table_of_contents get_knowledge_ingestion_status list_knowledge_documents
get_file_watcher_status get_ticket list_tickets get_system_metrics list_skills
search_tools get_tool_health_report get_zg_facets list_topics roms_titans_recall
roms_sieve_compact roms_symdex_lookup roms_shield_repair_json roms_prompt_lookup
memory_prepare_context memory_recall memory_get
search_codebase find_symbol_definition calculate_refund_amount
""".split())
WRITE_TOOLS = frozenset("""
refresh_knowledge_skills record_knowledge_skill_feedback
create_task_skill revise_saved_task_skill
save_task_skill record_task_skill_feedback forget_task_skill
add_knowledge_document queue_knowledge_text queue_knowledge_path knowledge_import_progress
retry_knowledge_import reload_knowledge create_support_ticket update_ticket_status
run_sandboxed_command add_skill distill_trajectory_to_skill autokarpathy_generate_dataset
 autokarpathy_optimize_prompt autokarpathy_eval_cartridge autoresearch roms_titans_remember
roms_titans_erase roms_snapshot_create roms_snapshot_rewind roms_shield_forecast
roms_decide roms_noul roms_score roms_bertopic_discover memory_retain
memory_record_verification memory_correct memory_retract memory_forget
""".split())
NETWORK_TOOLS = frozenset("""
draft_task_skill create_task_skill revise_saved_task_skill prepare_task_skill
search_knowledge_base search_grounded_context add_knowledge_document queue_knowledge_text
queue_knowledge_path knowledge_import_progress retry_knowledge_import reload_knowledge
 autokarpathy_optimize_prompt autokarpathy_eval_cartridge autoresearch run_sandboxed_command
""".split())
DESTRUCTIVE_TOOLS = frozenset({'roms_snapshot_rewind', 'roms_titans_erase', 'memory_forget', 'forget_task_skill'})


def tool_annotations(name):
    read = name in READ_TOOLS
    return dict(readOnlyHint=read, destructiveHint=not read, idempotentHint=read,
                openWorldHint=name in NETWORK_TOOLS or name not in READ_TOOLS | WRITE_TOOLS)


def plugin_allowed(path: Path, root: Path, *, reload=False):
    """Plugins execute host code; only operator-named modules are eligible."""
    if os.getenv('ROMS_MCP_PROFILE', 'read_only') != 'local':
        return False
    if reload and os.getenv('ROMS_MCP_HOT_RELOAD') != '1':
        return False
    names = {name.strip() for name in os.getenv('ROMS_MCP_PLUGINS', '').split(',') if name.strip()}
    if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name) for name in names):
        raise ValueError('ROMS_MCP_PLUGINS must contain comma-separated Python module names')
    return (path.stem in names and path.suffix == '.py' and not root.is_symlink()
            and not path.is_symlink() and path.is_file() and path.resolve().parent == root.resolve())
