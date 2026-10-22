"""Saved task-skill lifecycle over real SQLite and source ingestion."""
import asyncio
import json

import pytest
from app import task_skill_store as saved
from app.db import get_connection
from app.okf_loader import ingest_document_file
from tests.test_task_skills import setup


def save_fixture(tmp_path, monkeypatch):
    db, guide, prepared, skill = setup(tmp_path, monkeypatch)
    packet, authored = json.dumps(prepared['packet']), json.dumps(skill)
    result = saved.save(packet, authored, db_path=db)
    return db, guide, packet, skill, result


def test_save_reopen_search_and_retry_preserve_constraints(tmp_path, monkeypatch):
    db, _, packet, skill, first = save_fixture(tmp_path, monkeypatch)
    assert first['saved'] and first['persisted'] and not first['execution_ready']
    assert first['constraints'] == 'Require approval'
    assert not saved.save(packet, json.dumps(skill), db_path=db)['saved']
    assert saved.get(first['id'], db)['skill'] == skill
    assert saved.search('staging backup', db_path=db)['skills'][0]['id'] == first['id']
    assert not saved.search('missingword', db_path=db)['skills']
    with get_connection(db, reuse=False) as conn:
        manifest = json.loads(conn.execute('SELECT manifest_json FROM task_skill_candidates').fetchone()[0])
        assert all('text' not in source for source in manifest['sources'])


@pytest.mark.parametrize('change', ['edit', 'delete'])
def test_stale_saved_skill_withholds_body_and_export(tmp_path, monkeypatch, change):
    db, guide, packet, skill, first = save_fixture(tmp_path, monkeypatch)
    if change == 'edit':
        guide.write_text(guide.read_text() + '\nChanged approval requirements.\n')
        ingest_document_file(guide, db)
    else:
        with get_connection(db, reuse=False) as conn:
            conn.execute('DELETE FROM okf_registry')
    current = saved.get(first['id'], db)
    assert current['status'] == 'stale'
    assert current['constraints'] == json.loads(packet)['constraints']
    assert 'skill' not in current and 'markdown' not in current
    assert saved.search(db_path=db)['skills'][0]['status'] == 'stale'
    with pytest.raises(ValueError, match='stale'):
        saved.record_feedback(first['id'], 'helpful', 'late-feedback', db_path=db)
    with pytest.raises(ValueError, match='Source changed'):
        saved.save(packet, json.dumps(skill), db_path=db)


def test_feedback_is_idempotent_and_never_inherited_by_revision(tmp_path, monkeypatch):
    db, _, packet, skill, first = save_fixture(tmp_path, monkeypatch)
    args = (first['id'], 'needs_work', 'run-1', 'Clarify the validation step.', 'fixture:review-1')
    assert saved.record_feedback(*args, db_path=db)['recorded']
    assert not saved.record_feedback(*args, db_path=db)['recorded']
    with pytest.raises(ValueError, match='different feedback'):
        saved.record_feedback(first['id'], 'helpful', 'run-1', db_path=db)
    skill['title'] = 'Clarified staging backup'
    revision = saved.save(packet, json.dumps(skill), first['id'], db)
    assert revision['id'] != first['id'] and revision['parent_id'] == first['id']
    assert revision['feedback'] == {} and not revision['execution_ready']
    old = saved.get(first['id'], db)
    assert old['feedback'] == {'needs_work': 1}
    assert old['observations'][0]['evidence'] == 'fixture:review-1'
    with pytest.raises(ValueError, match='different immutable parent'):
        saved.save(packet, json.dumps(skill), db_path=db)


def test_unknowns_and_invalid_parent_roll_back_save(tmp_path, monkeypatch):
    db, _, prepared, skill = setup(tmp_path, monkeypatch)
    packet = json.dumps(prepared['packet'])
    with pytest.raises(ValueError, match='Parent candidate'):
        saved.save(packet, json.dumps(skill), 'task-' + 'f' * 24, db)
    assert saved.search(db_path=db)['total'] == 0
    skill['unknowns'] = ['Database path not supplied.']
    with pytest.raises(ValueError, match='Resolve unknowns'):
        saved.save(packet, json.dumps(skill), db_path=db)
    assert saved.search(db_path=db)['total'] == 0


def test_forget_removes_content_and_feedback_without_removing_descendant(tmp_path, monkeypatch):
    db, _, packet, skill, first = save_fixture(tmp_path, monkeypatch)
    saved.record_feedback(first['id'], 'helpful', 'review-1', db_path=db)
    skill['title'] = 'Revision'
    child = saved.save(packet, json.dumps(skill), first['id'], db)
    assert saved.forget(first['id'], db)['forgotten']
    assert not saved.forget(first['id'], db)['forgotten']
    assert saved.get(first['id'], db) is None
    assert saved.get(child['id'], db)['parent_id'] == first['id']
    assert not saved.save(packet, json.dumps(skill), first['id'], db)['saved']
    with get_connection(db, reuse=False) as conn:
        assert conn.execute('SELECT count(*) FROM task_skill_observations').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM okf_registry').fetchone()[0] > 0


def test_corrupted_saved_content_cannot_reuse_old_identity(tmp_path, monkeypatch):
    db, _, _, skill, first = save_fixture(tmp_path, monkeypatch)
    skill['steps'][0]['text'] = 'An altered procedure.'
    with get_connection(db, reuse=False) as conn:
        conn.execute('UPDATE task_skill_candidates SET skill_json=?', (json.dumps(skill),))
    with pytest.raises(ValueError, match='identity'):
        saved.get(first['id'], db)


def test_source_writer_cannot_change_evidence_between_validation_and_save(tmp_path, monkeypatch):
    db, _, prepared, skill = setup(tmp_path, monkeypatch)
    from app import task_skills
    original = task_skills.finalize
    attempts = []
    def competing_writer(packet, authored, **kwargs):
        assert kwargs['_connection'].in_transaction
        import sqlite3
        with sqlite3.connect(db, timeout=0.01) as other:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                other.execute("UPDATE okf_registry SET checksum='changed'")
        attempts.append(True)
        return original(packet, authored, **kwargs)
    monkeypatch.setattr(task_skills, 'finalize', competing_writer)
    result = saved.save(json.dumps(prepared['packet']), json.dumps(skill), db_path=db)
    assert result['saved'] and attempts


@pytest.mark.parametrize('structured', [False, True])
def test_mcp_saved_skill_capabilities_enforce_profile_and_delete_opt_in(tmp_path, monkeypatch, structured):
    db, _, prepared, skill = setup(tmp_path, monkeypatch)
    from app import db as database
    monkeypatch.setattr(database, 'DB_PATH', db)
    from fastmcp import Client, FastMCP
    from fastmcp.exceptions import ToolError
    from app.mcp_policy import MCPPolicy
    from app.knowledge_skill_tools import register_knowledge_skill_tools
    async def run():
        row = None
        for profile, destructive in [('read_only', False), ('local', False), ('local', True)]:
            server = FastMCP('saved-skills', middleware=[MCPPolicy(profile=profile, allow_destructive=destructive)])
            register_knowledge_skill_tools(server)
            async with Client(server) as client:
                encode = (lambda value: value) if structured else json.dumps
                args = {'packet_json': encode(prepared['packet']), 'skill_json': encode(skill)}
                if profile == 'read_only':
                    await client.call_tool('search_saved_task_skills', {})
                    with pytest.raises(ToolError, match='read_only'):
                        await client.call_tool('save_task_skill', args)
                    continue
                result = await client.call_tool('save_task_skill', args)
                row = json.loads(result.content[0].text)
                await client.call_tool('get_saved_task_skill', {'skill_id': row['id']})
                if not destructive:
                    with pytest.raises(ToolError, match='Destructive'):
                        await client.call_tool('forget_task_skill', {'skill_id': row['id']})
                else:
                    await client.call_tool('forget_task_skill', {'skill_id': row['id']})
        assert saved.get(row['id'], db) is None
    asyncio.run(run())


def test_mcp_structured_contract_advertises_fields_and_rejects_malformed_objects(tmp_path, monkeypatch):
    db, _, prepared, skill = setup(tmp_path, monkeypatch)
    from app import db as database
    monkeypatch.setattr(database, 'DB_PATH', db)
    from fastmcp import Client, FastMCP
    from fastmcp.exceptions import ToolError
    from app.knowledge_skill_tools import register_knowledge_skill_tools
    async def run():
        server = FastMCP('structured-task-contract')
        register_knowledge_skill_tools(server)
        async with Client(server) as client:
            advertised = {tool.name: tool.input_schema for tool in await client.list_tools()}
            for name in ('finalize_task_skill', 'save_task_skill'):
                shape = advertised[name]['properties']['packet_json']['anyOf'][0]
                assert set(shape['required']) == {'task', 'constraints', 'sources', 'revision'}
                assert shape['additionalProperties'] is False
                assert shape['properties']['sources']['items']['additionalProperties'] is False
                malformed = [{**prepared['packet'], 'contract': skill},
                             {'"' + key + '"': value for key, value in prepared['packet'].items()}]
                for packet in malformed:
                    with pytest.raises(ToolError):
                        await client.call_tool(name, {'packet_json': packet, 'skill_json': skill})
            assert saved.search(db_path=db)['total'] == 0
    asyncio.run(run())
