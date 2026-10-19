"""Exercise the compiled Mojo binary over MCP stdio using isolated state."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import hashlib
import sqlite3
import struct
import sqlite_vec
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def verify(binary: str, root: str) -> None:
    with tempfile.TemporaryDirectory(prefix='roms-protocol-') as temporary:
        state = Path(temporary)
        (state / 'knowledge').mkdir()
        (state / 'skills').mkdir()
        shutil.copy2(Path(root) / 'skills/customer_service.md', state / 'skills/customer_service.md')
        env = dict(os.environ, ROMS_MCP_PROFILE='local', ROMS_MCP_ALLOW_DESTRUCTIVE='1', ROMS_DATA_DIR=str(state / 'data'),
                   ROMS_DB_PATH=str(state / 'data/roms.db'),
                   ROMS_KNOWLEDGE_DIR=str(state / 'knowledge'),
                   ROMS_SKILLS_DIR=str(state / 'skills'),
                   PYTHONPATH=os.pathsep.join([root, os.environ.get('PYTHONPATH', '')]))
        params = StdioServerParameters(command=binary, args=[], env=env, cwd=root)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                assert initialized.model_dump(by_alias=True)["serverInfo"]["name"] == 'ROMS-Mojo-Engine'
                listing = await session.list_tools()
                names = {tool.name for tool in listing.tools}
                assert {'search_knowledge_base', 'create_support_ticket', 'get_ticket', 'update_ticket_status', 'list_tickets', 'search_tools', 'distill_trajectory_to_skill'} <= names
                assert {'memory_retain', 'memory_record_verification', 'memory_recall',
                        'memory_get', 'memory_correct', 'memory_retract', 'memory_forget'} <= names

                async def memory_call(name: str, arguments: dict[str, object]) -> dict[str, object]:
                    response = await session.call_tool(name, arguments)
                    assert not response.model_dump(by_alias=True).get('isError', False), response
                    return json.loads(''.join(getattr(item, 'text', '') for item in response.content))

                scope = {'project_id': 'mojo-protocol-fixture'}
                lesson = await memory_call('memory_retain', dict(scope,
                    summary='Keep the timezone when parsing dates', source_ref='fixture:source'))
                assert lesson['status'] == 'candidate'
                assert not (await memory_call('memory_recall', dict(scope, query='timezone')))['memories']
                checked = await memory_call('memory_record_verification', dict(scope,
                    memory_id=lesson['id'], command='fixture: simulated test result',
                    exit_code=0, evidence_ref='fixture:passed-check'))
                assert checked['recommendation_eligible'] is True
                recalled = await memory_call('memory_recall', dict(scope, query='timezone'))
                assert recalled['memories'][0]['id'] == lesson['id']
                assert not (await memory_call('memory_recall',
                    {'project_id': 'other-project', 'query': 'timezone'}))['memories']
                replacement = await memory_call('memory_correct', dict(scope, memory_id=lesson['id'],
                    summary='Preserve timezone and offset', source_ref='fixture:correction', reason='More precise'))
                assert replacement['status'] == 'candidate' and not replacement['recommendation_eligible']
                assert not (await memory_call('memory_recall', dict(scope, query='timezone')))['memories']
                previous = await memory_call('memory_get', dict(scope, memory_id=lesson['id']))
                assert previous['status'] == 'superseded'
                await memory_call('memory_retract', dict(scope, memory_id=replacement['id'], reason='Fixture cleanup'))
                await memory_call('memory_forget', dict(scope, memory_id=replacement['id']))
                assert 'caller-supplied' in str(await session.read_resource('skills://verified_memory'))
                assert 'candidate' in str(await session.get_prompt('verified_memory_sop'))
                assert 'memory_prepare_context' in names
                warning_id = ''
                for index in range(6):
                    item = await memory_call('memory_retain', dict(scope,
                        summary=f'Timezone case {index}: ' + 'preserve offsets ' * 20,
                        source_ref='fixture:context'))
                    await memory_call('memory_record_verification', dict(scope,
                        memory_id=item['id'], command='fixture: simulated check',
                        exit_code=1 if index == 0 else 0, evidence_ref='fixture:context-check'))
                    if index == 0:
                        warning_id = item['id']
                response = await session.call_tool('memory_prepare_context', dict(scope, query='timezone', max_chars=1500))
                assert not response.model_dump(by_alias=True).get('isError', False), response
                payload = ''.join(getattr(item, 'text', '') for item in response.content)
                bundle = json.loads(payload)
                assert len(payload) <= 1500
                assert bundle['backend'] == 'mojo' and bundle['warning_included']
                assert any(item['id'] == warning_id for item in bundle['records'])
                assert bundle['omitted'] > 0
                # A known vector/query pair exercises the native search handler
                # and SQLite without a model download or a substitute handler.
                query = 'bridge fixture policy'
                vector = struct.pack('384f', 1.0, *([0.0] * 383))
                connection = sqlite3.connect(state / 'data/roms.db')
                connection.enable_load_extension(True)
                sqlite_vec.load(connection)
                connection.enable_load_extension(False)
                connection.execute('INSERT INTO okf_registry(doc_id, title, doc_type) VALUES (?, ?, ?)', ('bridge.md', 'Bridge fixture', 'general'))
                connection.execute('INSERT INTO vec_chunks(chunk_id, doc_id, embedding, content) VALUES (?, ?, ?, ?)', (1, 'bridge.md', vector, 'Bridge fixture policy: verified source passage.'))
                connection.execute('INSERT INTO fts_chunks(chunk_id, doc_id, content) VALUES (?, ?, ?)', (1, 'bridge.md', 'Bridge fixture policy: verified source passage.'))
                from app.rag_engine import _embedding_namespace
                cache_payload = json.dumps((_embedding_namespace(), query), ensure_ascii=False)
                connection.execute('INSERT INTO embedding_cache(query_hash, embedding_blob) VALUES (?, ?)', (hashlib.sha256(cache_payload.encode()).hexdigest(), vector))
                connection.commit()
                connection.close()
                async def call(name, arguments, expected):
                    response = await session.call_tool(name, arguments)
                    assert not response.model_dump(by_alias=True).get("isError", False), response
                    result = '\n'.join(getattr(item, 'text', '') for item in response.content)
                    assert expected in result, result
                await call('create_support_ticket', {'ticket_id':'BRIDGE-001','email':'demo@example.com','summary':'Mojo bridge test'}, 'created successfully')
                await call('get_ticket', {'ticket_id':'BRIDGE-001'}, 'BRIDGE-001')
                await call('update_ticket_status', {'ticket_id':'BRIDGE-001','status':'RESOLVED'}, 'RESOLVED')
                await call('list_tickets', {'status':'RESOLVED'}, 'BRIDGE-001')
                await call('get_ticket', {'ticket_id':'does-not-exist'}, 'not found')
                await call('search_knowledge_base', {'query':query, 'limit':1}, 'bridge.md')
                response = await session.call_tool('search_knowledge_base', {'query':'example','limit':0})
                assert response.model_dump(by_alias=True).get("isError", False)
                resource = await session.read_resource('skills://customer_service')
                assert 'Customer Service' in str(resource)
                prompt = await session.get_prompt('customer_service_sop')
                assert 'Customer Service' in str(prompt)
                print(json.dumps({'server': initialized.model_dump(by_alias=True)["serverInfo"]["name"], 'tools': sorted(names), 'native_context_budget_and_warning':'passed', 'memory_lifecycle':'passed', 'memory_scope':'passed', 'ticket_lifecycle':'passed', 'native_search_fixture':'passed', 'resource':'passed', 'prompt':'passed', 'invalid_limit':'rejected'}))
        obstacle = state / 'not-a-directory'
        obstacle.write_text('fixture', encoding='utf-8')
        failed_env = dict(env, ROMS_DB_PATH=str(obstacle / 'roms.db'))
        process = await asyncio.create_subprocess_exec(binary, cwd=root, env=failed_env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        assert process.returncode != 0, stderr.decode(errors='replace')
        assert stdout == b'', stdout
        print(json.dumps({'startup_failure_exit':'nonzero', 'stdout':'clean'}))

if __name__ == '__main__':
    asyncio.run(asyncio.wait_for(verify(sys.argv[1], sys.argv[2]), timeout=120))
