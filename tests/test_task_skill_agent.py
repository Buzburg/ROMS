"""Workflow decisions and persistence are owned by ROMS, not generated prose."""
import asyncio
import copy
import json

import pytest
from app import task_skill_agent as agent
from app import task_skill_store as saved
from app.okf_loader import ingest_document_file
from tests.test_task_skills import setup


def fixture(tmp_path, monkeypatch):
    db, guide, prepared, skill = setup(tmp_path, monkeypatch)
    monkeypatch.setenv('ROMS_AUTHORING_ENDPOINT', 'http://127.0.0.1:18973/v1')
    monkeypatch.setenv('ROMS_AUTHORING_MODEL', 'fixture')
    calls = []
    async def generate(*args, **kwargs):
        calls.append(args)
        if len(calls) % 3 == 1:
            return {'reason': 'The sources support this task.', 'sources_compatible': True,
                    'relevant_evidence': True, 'missing_inputs': []}
        return copy.deepcopy(skill)
    monkeypatch.setattr(agent, 'generate', generate)
    return db, guide, prepared, skill, calls


def test_author_saves_real_receipt_and_reuses_only_current_evidence(tmp_path, monkeypatch):
    db, guide, prepared, _, calls = fixture(tmp_path, monkeypatch)
    task, constraints = prepared['packet']['task'], prepared['packet']['constraints']
    first = asyncio.run(agent.author(task, constraints, retain=True, db_path=db))
    assert first['persisted'] and first['generation_steps'] == 3 and len(calls) == 3
    assert first['review']['required'] and first['review']['checklist']
    assert saved.get(first['id'], db)['status'] == 'candidate'
    repeated = asyncio.run(agent.author(task, constraints, retain=True, db_path=db))
    assert repeated['id'] == first['id'] and repeated['reused'] and len(calls) == 3
    saved.record_feedback(first['id'], 'needs_work', 'review-1', db_path=db)
    asyncio.run(agent.author(task, constraints, retain=True, db_path=db))
    assert len(calls) == 6  # Adverse feedback prevents silent reuse.
    guide.write_text(guide.read_text() + '\nKeep the backup encrypted.\n')
    ingest_document_file(guide, db)
    child = asyncio.run(agent.author('', retain=True, parent_id=first['id'], db_path=db))
    assert child['parent_id'] == first['id'] and child['id'] != first['id']
    assert child['constraints'] == constraints and child['feedback'] == {}
    assert saved.get(first['id'], db)['status'] == 'stale'


def test_draft_does_not_persist_and_blockers_stop_generation(tmp_path, monkeypatch):
    db, _, prepared, _, calls = fixture(tmp_path, monkeypatch)
    result = asyncio.run(agent.author(prepared['packet']['task'], db_path=db))
    assert result['status'] == 'candidate' and not result['persisted']
    assert saved.search(db_path=db)['total'] == 0
    async def conflicting(*args, **kwargs):
        calls.append(args)
        return {'reason': 'Two sources require opposing actions.', 'sources_compatible': False,
                'relevant_evidence': True, 'missing_inputs': []}
    monkeypatch.setattr(agent, 'generate', conflicting)
    result = asyncio.run(agent.author(prepared['packet']['task'], retain=True, db_path=db))
    assert result['status'] == 'needs_information' and result['generation_steps'] == 1
    assert result['sources'] == [{k: v for k, v in s.items() if k != 'text'}
                                 for s in prepared['packet']['sources']]
    assert len(calls) == 4 and saved.search(db_path=db)['total'] == 0


@pytest.mark.parametrize('failure', ['unknowns', 'source_change', 'cancel'])
def test_review_failure_never_saves(tmp_path, monkeypatch, failure):
    db, guide, prepared, skill, _ = fixture(tmp_path, monkeypatch)
    count = 0
    async def generate(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            return {'reason': 'Supported.', 'sources_compatible': True,
                    'relevant_evidence': True, 'missing_inputs': []}
        if count == 3:
            if failure == 'cancel':
                raise asyncio.CancelledError()
            if failure == 'source_change':
                guide.write_text(guide.read_text() + '\nChanged source.\n')
                ingest_document_file(guide, db)
            if failure == 'unknowns':
                return {'status': 'needs_information', 'questions': ['Which source applies?']}
        return copy.deepcopy(skill)
    monkeypatch.setattr(agent, 'generate', generate)
    request = agent.author(prepared['packet']['task'], retain=True, db_path=db)
    if failure == 'cancel':
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(request)
    elif failure == 'source_change':
        with pytest.raises(ValueError, match='Source changed'):
            asyncio.run(request)
    else:
        assert asyncio.run(request)['status'] == 'needs_information'
    assert saved.search(db_path=db)['total'] == 0


@pytest.mark.parametrize('endpoint', ['https://127.0.0.1:1/v1', 'http://localhost:1/v1',
    'http://192.168.1.2:1/v1', 'http://user:pass@127.0.0.1:1/v1', 'http://127.0.0.1:1/v1?x=1'])
def test_configuration_rejects_remote_or_ambiguous_endpoints(monkeypatch, endpoint):
    monkeypatch.setenv('ROMS_AUTHORING_ENDPOINT', endpoint)
    monkeypatch.setenv('ROMS_AUTHORING_MODEL', 'fixture')
    with pytest.raises(ValueError):
        agent.configuration()


@pytest.mark.parametrize('mode', ['json', 'redirect', 'unfinished', 'oversized'])
def test_local_http_generation_protocol(tmp_path, mode):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(302 if mode == 'redirect' else 200)
            if mode == 'redirect':
                self.send_header('Location', 'http://192.0.2.1/v1/chat/completions')
            self.end_headers()
            content = 'x' * 140000 if mode == 'oversized' else json.dumps({'answer': 'fixture'})
            self.wfile.write(json.dumps({'choices': [{'finish_reason': 'length' if mode == 'unfinished' else 'stop',
                'message': {'content': content}}]}).encode())
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        request = agent.generate(f'http://127.0.0.1:{server.server_port}/v1', 'fixture',
                                 'Return JSON.', {'task': 'fixture'}, {'type': 'object'})
        if mode == 'json':
            assert asyncio.run(request) == {'answer': 'fixture'}
        else:
            with pytest.raises(ValueError):
                asyncio.run(request)
        assert len(requests) == 1 and 'tools' not in requests[0]
        assert requests[0]['response_format']['type'] == 'json_schema'
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_mcp_workflow_write_policy_and_read_only_drafting(tmp_path, monkeypatch):
    db, _, prepared, _, calls = fixture(tmp_path, monkeypatch)
    from app import db as database
    monkeypatch.setattr(database, 'DB_PATH', db)
    from fastmcp import Client, FastMCP
    from fastmcp.exceptions import ToolError
    from app.mcp_policy import MCPPolicy
    from app.knowledge_skill_tools import register_knowledge_skill_tools
    async def run():
        server = FastMCP('bounded-read', middleware=[MCPPolicy(profile='read_only')])
        register_knowledge_skill_tools(server)
        args = {'task': prepared['packet']['task'], 'constraints': prepared['packet']['constraints']}
        async with Client(server) as client:
            with pytest.raises(ToolError, match='read_only'):
                await client.call_tool('create_task_skill', args)
            assert not calls
            result = await client.call_tool('draft_task_skill', args)
            assert not json.loads(result.content[0].text)['persisted']
            assert saved.search(db_path=db)['total'] == 0
        server = FastMCP('bounded-local', middleware=[MCPPolicy(profile='local')])
        register_knowledge_skill_tools(server)
        async with Client(server) as client:
            result = await client.call_tool('create_task_skill', args)
            assert json.loads(result.content[0].text)['persisted']
    asyncio.run(run())


def test_new_retrieved_document_prevents_old_evidence_reuse(tmp_path, monkeypatch):
    db, guide, prepared, _, calls = fixture(tmp_path, monkeypatch)
    task, constraints = prepared['packet']['task'], prepared['packet']['constraints']
    old = asyncio.run(agent.author(task, constraints, retain=True, db_path=db))
    extra = guide.parent/'additional.md'
    extra.write_text('# Staging backups\nCheck available disk space before copying.\n')
    ingest_document_file(extra, db)
    from app import rag_engine
    monkeypatch.setattr(rag_engine, 'local_search', lambda *a, **k: [
        {'doc_id': 'guide.md'}, {'doc_id': 'additional.md'}])
    new = asyncio.run(agent.author(task, constraints, retain=True, db_path=db))
    assert not new['reused'] and new['source_revision'] != old['source_revision']
    assert len(calls) == 6


def test_unchanged_revision_returns_existing_candidate_without_self_parent(tmp_path, monkeypatch):
    db, _, prepared, _, calls = fixture(tmp_path, monkeypatch)
    first = asyncio.run(agent.author(prepared['packet']['task'], prepared['packet']['constraints'],
                                     retain=True, db_path=db))
    same = asyncio.run(agent.author('', retain=True, parent_id=first['id'], db_path=db))
    assert same['id'] == first['id'] and same['revision_unchanged']
    assert same['parent_id'] is None and saved.search(db_path=db)['total'] == 1
    assert not same['model_called'] and len(calls) == 3
    saved.record_feedback(first['id'], 'needs_work', 'review', db_path=db)
    same = asyncio.run(agent.author('', retain=True, parent_id=first['id'], db_path=db))
    assert same['revision_unchanged'] and same['model_called'] and len(calls) == 6
    assert same['feedback'] == {'needs_work': 1}


def test_empty_library_preserves_insufficient_evidence_without_model_calls(tmp_path, monkeypatch):
    db, _, _, _, calls = fixture(tmp_path, monkeypatch)
    from app import rag_engine
    monkeypatch.setattr(rag_engine, 'local_search', lambda *a, **k: [])
    result = asyncio.run(agent.author('Explain a backup', retain=True, db_path=db))
    assert result['status'] == 'insufficient_evidence' and result['questions']
    assert not result['persisted'] and not result['model_called'] and not calls


def test_revision_name_resolution_uses_unique_leaf_and_rejects_ambiguity(tmp_path, monkeypatch):
    db, guide, prepared, skill, _ = fixture(tmp_path, monkeypatch)
    first = asyncio.run(agent.author(prepared['packet']['task'], prepared['packet']['constraints'],
                                     retain=True, db_path=db))
    assert asyncio.run(agent.revise('staging backup', db))['id'] == first['id']
    guide.write_text(guide.read_text() + '\nKeep the backup encrypted.\n')
    ingest_document_file(guide, db)
    child = asyncio.run(agent.revise('staging backup', db))
    assert child['parent_id'] == first['id']
    assert asyncio.run(agent.revise('staging backup', db))['id'] == child['id']
    other = agent.tasks.prepare('Another staging backup task', db_path=db)
    saved.save(json.dumps(other['packet']), json.dumps(skill), db_path=db)
    ambiguous = asyncio.run(agent.revise('staging backup', db))
    assert ambiguous['status'] == 'needs_information' and ambiguous['total_matches'] == 3
    assert not ambiguous['model_called'] and not ambiguous['persisted']
    assert asyncio.run(agent.revise('nonexistent', db))['total_matches'] == 0
