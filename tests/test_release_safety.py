"""Offline regression tests for release boundaries; no model or backend required."""
import asyncio
from pathlib import Path
import pytest
from starlette.testclient import TestClient
from app.safe_paths import markdown_path


@pytest.mark.parametrize('name', ['../outside', '..\\outside', '/absolute', 'C:\\outside', 'file:stream', 'CON', 'NUL.md', '', '.hidden', 'a/b', 'a\\b'])
def test_rejects_unsafe_document_names(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError):
        markdown_path(tmp_path, name)


def test_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / 'skills'
    root.mkdir()
    outside = tmp_path / 'outside.md'
    outside.write_text('private', encoding='utf-8')
    try:
        (root / 'linked.md').symlink_to(outside)
    except OSError:
        pytest.skip('Host does not permit creating symlinks')
    with pytest.raises(ValueError):
        markdown_path(root, 'linked')
    assert outside.read_text(encoding='utf-8') == 'private'


def test_knowledge_and_skills_stay_in_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import tools
    import frontmatter
    monkeypatch.setattr(tools, 'KNOWLEDGE_DIR', tmp_path / 'knowledge')
    monkeypatch.setattr(tools, 'SKILLS_DIR', tmp_path / 'skills')
    monkeypatch.setattr(tools, 'ingest_okf_file', lambda *a, **kw: True)
    with pytest.raises(ValueError):
        tools.add_skill('../outside', 'unwanted')
    with pytest.raises(ValueError):
        tools.add_knowledge_document('../outside', 'unwanted')
    title = 'Quoted "title"\nextra: metadata'
    tools.add_knowledge_document('safe', 'Example body', title=title)
    post = frontmatter.load(tmp_path / 'knowledge' / 'safe.md')
    assert post['title'] == title
    assert 'extra' not in post.metadata
    assert not (tmp_path / 'outside.md').exists()


def test_skill_resource_rejects_traversal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app import server
    monkeypatch.setattr(server, 'SKILLS_DIR', tmp_path)
    with pytest.raises(ValueError):
        server.get_skill_resource('../private')


def test_distilled_skill_rejects_traversal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app import trajectory_recorder as recorder
    monkeypatch.setattr(recorder, 'get_trajectory', lambda *a, **kw: {
        'goal': 'example', 'steps': [], 'success': True, 'final_result': 'done',
    })
    with pytest.raises(ValueError):
        recorder.distill_trajectory_to_skill('session', '../outside', target_skills_dir=tmp_path / 'skills')
    assert not (tmp_path / 'outside.md').exists()


@pytest.mark.parametrize('body', [[], None, {'messages': 'text'}, {'messages': [None]}, {'messages': [{'role': 'user', 'content': []}]}, {'messages': [], 'stream': 'false'}])
def test_gateway_rejects_invalid_shapes(body: object) -> None:
    from app.gateway import app
    with TestClient(app) as client:
        response = client.post('/v1/chat/completions', json=body)
    assert response.status_code == 400


def test_gateway_does_not_reuse_completions(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import gateway
    import httpx
    sent = []

    class Backend:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json, **kwargs):
            sent.append(json)
            return httpx.Response(200, json={'id': str(len(sent)), 'model': json['model']})

    monkeypatch.setattr(gateway.httpx, 'AsyncClient', Backend)
    monkeypatch.setattr(gateway, 'local_search', lambda **kw: [])
    monkeypatch.setattr(gateway, '_find_matching_skill', lambda query: None)
    monkeypatch.setattr(gateway, 'format_tool_search_results', lambda *a, **kw: '')
    monkeypatch.setattr(gateway, 'start_session', lambda **kw: None)
    monkeypatch.setattr(gateway, 'finish_session', lambda **kw: None)
    with TestClient(gateway.app) as client:
        for model in ['model-a', 'model-b', 'model-a']:
            response = client.post('/v1/chat/completions', json={
                'model': model, 'messages': [{'role': 'user', 'content': 'hello'}],
            })
            assert response.status_code == 200
            assert response.json()['model'] == model
            assert response.headers['X-ROMS-Cache'] == 'DISABLED'
    assert len(sent) == 3


def test_gateway_start_initializes_local_state(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import gateway, db, tool_rag, okf_loader, config
    import uvicorn
    events = []
    monkeypatch.setattr(db, 'init_database', lambda: events.append('database'))
    monkeypatch.setattr(tool_rag, 'init_default_tool_registry', lambda: events.append('tools'))
    monkeypatch.setattr(okf_loader, 'ingest_okf_directory', lambda path: events.append('knowledge'))
    monkeypatch.setattr(config, 'EMBEDDING_PROVIDER', 'local')
    monkeypatch.setattr(config, 'get_embedding_model', lambda: events.append('embedding'))
    monkeypatch.setattr(uvicorn, 'run', lambda app, **kw: events.append(kw['host']))
    gateway.start_gateway()
    assert events == ['database', 'tools', 'knowledge', 'embedding', '127.0.0.1']


def test_mcp_startup_keeps_stdout_clean(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    from app import server
    from app import knowledge_skills
    backfills = []
    monkeypatch.setattr(knowledge_skills, 'rebuild', lambda: backfills.append(True))
    monkeypatch.setattr(server, 'init_database', lambda: None)
    monkeypatch.setattr(server, '_init_default_tool_registry', lambda: None)
    monkeypatch.setattr(server, 'ingest_okf_directory', lambda path: 0)
    monkeypatch.setattr(server, 'load_custom_tools', lambda: None)
    monkeypatch.setattr(server, 'start_watcher', lambda mcp: None)
    transports = []
    monkeypatch.setattr(server.mcp, 'run', lambda *, transport: transports.append(transport))
    server.start_server()
    assert transports == ['stdio']
    assert backfills == [True]
    output = capsys.readouterr()
    assert output.out == ''
    assert 'Starting FastMCP' in output.err


def test_execution_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import tools
    monkeypatch.delenv('ROMS_ENABLE_EXPERIMENTAL_EXECUTION', raising=False)
    result = asyncio.run(tools.run_sandboxed_command.__wrapped__('unused', 'unused'))
    assert 'disabled' in result
    assert 'disabled' in tools.execute_tool_task('unused', 'unused', 'unused')
