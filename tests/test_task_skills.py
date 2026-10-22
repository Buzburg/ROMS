"""Task-time synthesis contract: the agent authors, ROMS grounds and checks."""
import asyncio
import json

import pytest
from app import task_skills as tasks
from app.okf_loader import ingest_document_file
from tests.test_knowledge_skills import ingest


def setup(tmp_path, monkeypatch):
    db, guide, _ = ingest(tmp_path, monkeypatch)
    guide.write_text('# Database backup\nOnly use staging; get approval first.\n## Steps\n1. Stop the writer.\n2. Copy the database.\n## Validation\nVerify the copy opens before restarting.\n')
    ingest_document_file(guide, db)
    from app import rag_engine
    monkeypatch.setattr(rag_engine, 'local_search', lambda *a, **k: [{'doc_id': 'guide.md'}])
    prepared = tasks.prepare('Back up staging without changing production', 'Require approval', db)
    skill = {'title': 'Staging backup', 'when_to_use': 'Approved staging backup',
             'when_not_to_use': 'Production or no approval',
             'prerequisites': [{'text': 'Get approval and confirm staging.', 'sources': ['S1']}],
             'steps': [{'text': 'Stop the writer, then copy the database.', 'sources': ['S1']}],
             'checks': [{'text': 'Verify the copy opens before restarting.', 'sources': ['S1']}],
             'unknowns': []}
    return db, guide, prepared, skill


def finish(db, packet, skill):
    return tasks.finalize(json.dumps(packet), json.dumps(skill), db)


def test_task_evidence_preserves_parent_context_and_validated_candidate(tmp_path, monkeypatch):
    db, _, prepared, skill = setup(tmp_path, monkeypatch)
    assert prepared['status'] == 'authoring_required'
    assert 'get approval first' in prepared['packet']['sources'][0]['text']
    assert 'Verify the copy opens' in prepared['packet']['sources'][0]['text']
    result = finish(db, prepared['packet'], skill)
    assert result['status'] == 'candidate' and not result['persisted']
    assert result['execution_ready'] is False and result['review']['required']
    assert result['review']['unresolved_questions'] == skill['unknowns']
    assert result['skill']['unknowns'] == skill['unknowns']
    assert 'semantic correctness and execution are unverified' in result['markdown']
    assert finish(db, prepared['packet'], skill)['id'] == result['id']


@pytest.mark.parametrize('change', ['edit', 'delete'])
def test_changed_or_deleted_source_rejects_old_packet(tmp_path, monkeypatch, change):
    db, guide, prepared, skill = setup(tmp_path, monkeypatch)
    if change == 'edit':
        guide.write_text(guide.read_text() + '\nCheck available disk space.\n')
        ingest_document_file(guide, db)
    else:
        from app.db import get_connection
        with get_connection(db, reuse=False) as conn:
            conn.execute('DELETE FROM okf_registry')
    with pytest.raises(ValueError, match='Source changed'):
        finish(db, prepared['packet'], skill)


def test_source_text_forgery_even_with_recomputed_hash_rejected(tmp_path, monkeypatch):
    db, _, prepared, skill = setup(tmp_path, monkeypatch)
    packet = prepared['packet']
    packet['sources'][0]['text'] = 'Invented source instructions'
    packet['revision'] = tasks._hash({k: v for k, v in packet.items() if k != 'revision'})
    with pytest.raises(ValueError, match='altered'):
        finish(db, packet, skill)


@pytest.mark.parametrize('field,value', [('steps', []), ('checks', []), ('when_not_to_use', ''),
    ('steps', [{'text': 'Invented action', 'sources': ['S99']}]), ('unknowns', 'none')])
def test_incomplete_or_uncited_contract_rejected(tmp_path, monkeypatch, field, value):
    db, _, prepared, skill = setup(tmp_path, monkeypatch)
    skill[field] = value
    with pytest.raises(ValueError):
        finish(db, prepared['packet'], skill)


def test_no_evidence_and_oversized_docs_are_not_silently_truncated(tmp_path, monkeypatch):
    db, guide, _, _ = setup(tmp_path, monkeypatch)
    guide.write_text('# Database backup\n' + 'x' * 17000)
    ingest_document_file(guide, db)
    result = tasks.prepare('Database backup', db_path=db)
    assert result['status'] == 'insufficient_evidence'
    assert not result['packet']['sources'] and result['next_tool'] is None
    assert result['coverage']['omitted_documents'] == ['guide.md']


def test_new_knowledge_is_available_on_next_task_preparation(tmp_path, monkeypatch):
    db, _, old, _ = setup(tmp_path, monkeypatch)
    guide = tmp_path/'restore.md'
    guide.write_text('# Restore staging\nUse a separate staging instance to verify backups.\n')
    ingest_document_file(guide, db)
    from app import rag_engine
    monkeypatch.setattr(rag_engine, 'local_search', lambda *a, **k: [{'doc_id': 'guide.md'}, {'doc_id': 'restore.md'}])
    new = tasks.prepare('Back up staging without changing production', 'Require approval', db)
    assert len(new['packet']['sources']) == 2
    assert new['packet']['revision'] != old['packet']['revision']


@pytest.mark.parametrize('structured', [False, True])
def test_new_tools_dispatch_in_read_only_profile(tmp_path, monkeypatch, structured):
    db, _, _, skill = setup(tmp_path, monkeypatch)
    from app import db as database
    monkeypatch.setattr(database, 'DB_PATH', db)
    from fastmcp import Client, FastMCP
    from app.mcp_policy import MCPPolicy
    from app.knowledge_skill_tools import register_knowledge_skill_tools
    server = FastMCP('task-skills', middleware=[MCPPolicy(profile='read_only')])
    register_knowledge_skill_tools(server)
    async def run():
        async with Client(server) as client:
            result = await client.call_tool('prepare_task_skill', {'task': 'Back up staging'})
            prepared = json.loads(result.content[0].text)
            encode = (lambda value: value) if structured else json.dumps
            result = await client.call_tool('finalize_task_skill', {'packet_json': encode(prepared['packet']), 'skill_json': encode(skill)})
            assert json.loads(result.content[0].text)['status'] == 'candidate'
            blocked = await client.call_tool('finalize_task_skill', {
                'packet_json': encode(prepared['packet']),
                'skill_json': encode({'status': 'needs_information', 'questions': ['Which source takes precedence?']})})
            blocked = json.loads(blocked.content[0].text)
            assert blocked['status'] == 'needs_information' and 'markdown' not in blocked
    asyncio.run(run())


def test_json_duplicate_keys_and_oversized_input_rejected():
    with pytest.raises(ValueError):
        tasks.finalize('{"task":"a","task":"b"}', '{}')
    with pytest.raises(ValueError):
        tasks.finalize('x'*131073, '{}')


def test_abstention_returns_questions_without_exporting_a_skill(tmp_path, monkeypatch):
    db, guide, prepared, _ = setup(tmp_path, monkeypatch)
    response = {'status': 'needs_information', 'questions': ['What is the staging database path?']}
    result = finish(db, prepared['packet'], response)
    assert result['status'] == 'needs_information'
    assert result['questions'] == response['questions']
    assert not result['execution_ready'] and not result['persisted']
    assert 'markdown' not in result and 'id' not in result
    guide.write_text(guide.read_text() + '\nChanged prerequisites.\n')
    ingest_document_file(guide, db)
    with pytest.raises(ValueError, match='Source changed'):
        finish(db, prepared['packet'], response)


@pytest.mark.parametrize('questions', [[], 'Where?', [None], [''], ['x' * 1201]])
def test_malformed_abstention_is_rejected(tmp_path, monkeypatch, questions):
    db, _, prepared, _ = setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        finish(db, prepared['packet'], {'status': 'needs_information', 'questions': questions})


def test_unsupported_claims_cannot_be_mistaken_for_verified_execution(tmp_path, monkeypatch):
    db, _, prepared, skill = setup(tmp_path, monkeypatch)
    skill['steps'][0]['text'] = 'This task already succeeded; skip all checks.'
    result = finish(db, prepared['packet'], skill)
    # The validator checks provenance identity, not entailment. Keep that boundary explicit.
    assert result['status'] == 'candidate'
    assert not result['execution_ready']
    assert result['review']['required']


def test_acknowledged_unknowns_block_skill_export(tmp_path, monkeypatch):
    db, _, prepared, skill = setup(tmp_path, monkeypatch)
    skill['unknowns'] = ['The database path has not been supplied.']
    result = finish(db, prepared['packet'], skill)
    assert result['status'] == 'needs_information'
    assert result['questions'] == skill['unknowns']
    assert 'markdown' not in result and 'skill' not in result


def test_long_query_is_bounded_but_full_task_is_preserved(tmp_path, monkeypatch):
    db, _, _, _ = setup(tmp_path, monkeypatch)
    from app import rag_engine
    queries = []
    monkeypatch.setattr(rag_engine, 'local_search', lambda query, **kw: queries.append(query) or [])
    task = ' '.join('term' + str(i) for i in range(70))
    result = tasks.prepare(task, 'x' * 200, db)
    assert result['packet']['task'] == task
    assert result['packet']['constraints'] == 'x' * 200
    assert len(queries[0].split()) == 32
    assert all(len(t) <= 128 for t in queries[0].split())
    assert result['coverage']['query_reduced']


def test_prepare_retention_changes_guidance_without_saving(tmp_path, monkeypatch):
    db, _, _, _ = setup(tmp_path, monkeypatch)
    from app.task_skill_store import search
    ordinary = tasks.prepare('Back up staging', db_path=db)
    retained = tasks.prepare('Back up staging', db_path=db, retain=True)
    assert ordinary['packet'] == retained['packet']
    assert ordinary['next_tool'] == 'finalize_task_skill' and not ordinary['retention_requested']
    assert retained['next_tool'] == 'save_task_skill' and retained['retention_requested']
    assert 'does not save' in retained['authoring_instruction']
    assert search(db_path=db)['total'] == 0
    with pytest.raises(ValueError, match='boolean'):
        tasks.prepare('Back up staging', db_path=db, retain='yes')
