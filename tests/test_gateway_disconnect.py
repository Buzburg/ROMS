"""Real TCP disconnects through the ASGI middleware close upstream HTTP work."""
import asyncio
from contextlib import asynccontextmanager
import json
import socket

import httpx
import pytest
import uvicorn

from app import gateway, project_model


@asynccontextmanager
async def serving(app):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(16)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, lifespan='off', log_level='error'))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                assert not task.done()
                await asyncio.sleep(0.01)
        yield port
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        listener.close()


@pytest.mark.parametrize('mode', ['nonstream', 'stream', 'draft', 'scoped'])
def test_client_disconnect_closes_actual_upstream_socket_and_allows_next_request(monkeypatch, mode):
    monkeypatch.setenv('ROMS_RECORD_CHAT_TRAJECTORIES', '1')
    monkeypatch.setenv('ROMS_GATEWAY_API_KEY', 'fixture-key')
    monkeypatch.setenv('ROMS_UPSTREAM_API_KEY', 'fixture-upstream-key')
    def retrieve(**kwargs):
        assert mode != 'scoped', 'Scoped context must not trigger unscoped retrieval'
        return []
    monkeypatch.setattr(gateway, 'local_search', retrieve)
    monkeypatch.setattr(gateway, 'start_session', lambda **_: None)
    finished = []
    monkeypatch.setattr(gateway, 'finish_session', lambda **record: finished.append(record))

    async def check():
        started, closed = asyncio.Event(), asyncio.Event()
        active = set()
        async def upstream(reader, writer):
            task = asyncio.current_task()
            active.add(task)
            try:
                headers = await reader.readuntil(b'\r\n\r\n')
                path = headers.split(b' ')[1].decode()
                length = next(int(line.split(b':', 1)[1]) for line in headers.split(b'\r\n') if line.lower().startswith(b'content-length:'))
                body = json.loads(await reader.readexactly(length))
                assert 'roms_retrieval' not in body, 'Gateway-only options leaked upstream'
                if path == '/apply-template':
                    response = {'prompt': 'fixture'}
                elif path == '/tokenize':
                    response = {'tokens': [1]}
                elif next((item.get('content') for item in reversed(body.get('messages', []))
                           if item.get('role') == 'user'), None) == 'quick':
                    assert closed.is_set(), 'The cancelled upstream connection remained open'
                    response = {'model': 'fixture', 'choices': [{'message': {'content': 'ready'}, 'finish_reason': 'stop'}]}
                else:
                    started.set()
                    if body.get('stream'):
                        writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n')
                        chunk = b'data: {"fixture":"started"}\n\n'
                        writer.write(f'{len(chunk):x}\r\n'.encode() + chunk + b'\r\n')
                        await writer.drain()
                    assert await reader.read(1) == b''
                    closed.set()
                    return
                encoded = json.dumps(response).encode()
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: ' + str(len(encoded)).encode() + b'\r\n\r\n' + encoded)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
                active.discard(task)

        backend = await asyncio.start_server(upstream, '127.0.0.1', 0)
        origin = f'http://127.0.0.1:{backend.sockets[0].getsockname()[1]}'
        monkeypatch.setattr(gateway, 'ROMS_UPSTREAM_LLM_URL', origin + '/v1')
        monkeypatch.setattr(project_model, 'ROMS_UPSTREAM_LLM_URL', origin + '/v1')
        try:
            async with backend, serving(gateway.app) as port:
                reader, writer = await asyncio.open_connection('127.0.0.1', port)
                payload = ({'instruction': 'Set VALUE to 2', 'files': {'module.py': 'VALUE = 1\n'}} if mode == 'draft' else
                           {'messages': [{'role': 'user', 'content': 'wait until cancelled'}], 'stream': mode == 'stream'})
                path = '/v1/project/draft' if mode == 'draft' else '/v1/chat/completions'
                if mode == 'scoped':
                    payload['roms_retrieval'] = 'disabled'
                encoded = json.dumps(payload).encode()
                writer.write(f'POST {path} HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer fixture-key\r\nContent-Type: application/json\r\nContent-Length: {len(encoded)}\r\n\r\n'.encode() + encoded)
                await writer.drain()
                try:
                    await asyncio.wait_for(started.wait(), 3)
                    if mode == 'stream':
                        await asyncio.wait_for(reader.readuntil(b'fixture'), 3)
                finally:
                    writer.close()
                    await writer.wait_closed()
                await asyncio.wait_for(closed.wait(), 3)
                async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
                    response = await client.post(f'http://127.0.0.1:{port}/v1/chat/completions',
                        headers={'Authorization': 'Bearer fixture-key'},
                        json={'messages': [{'role': 'user', 'content': 'quick'}],
                              **({'roms_retrieval': 'disabled'} if mode == 'scoped' else {})})
                    assert response.status_code == 200, response.text
                    assert response.json()['choices'][0]['message']['content'] == 'ready'
                if mode != 'draft':
                    assert len(finished) == 2 and finished[0]['success'] is False and finished[1]['success'] is True
                    assert 'closed' in finished[0]['final_result']
        finally:
            for task in active.copy():
                task.cancel()
            await asyncio.gather(*active, return_exceptions=True)
    asyncio.run(check())
