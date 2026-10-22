"""Real subprocess ownership, output bounds and native broker model integration."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import sys
import socket
import subprocess
import time

import pytest
import psutil

from app import memory, native_chat
from app.broker_protocol import ProtocolError
from test_broker_chat import native_chat as native_broker
from test_broker_memory import database, contents
from test_broker_concurrency import payload, response


def executable(tmp_path, source):
    path = tmp_path / 'controlled worker'
    path.write_text('#!' + sys.executable + '\n' + source)
    path.chmod(0o700)
    return path


def test_worker_environment_excludes_credentials(monkeypatch):
    for name in ('ROMS_GATEWAY_API_KEY', 'ROMS_UPSTREAM_API_KEY', 'LLAMA_API_KEY', 'AWS_SECRET_ACCESS_KEY', 'LD_PRELOAD'):
        monkeypatch.setenv(name, 'fixture-secret')
        assert name not in native_chat.environment()


@pytest.mark.parametrize('mode', ['cancel', 'stubborn', 'timeout', 'output'])
def test_owned_child_disappears_on_cancel_timeout_or_output_overflow(tmp_path, monkeypatch, mode):
    marker = tmp_path / 'pid'
    source = ('import os,time,sys,signal\nfrom pathlib import Path\n' +
              ('signal.signal(signal.SIGTERM, signal.SIG_IGN)\n' if mode == 'stubborn' else '') +
              f'pending = Path({str(marker.with_suffix(".pending"))!r})\n' +
              'pending.write_text(str(os.getpid()))\n' +
              f'pending.replace({str(marker)!r})\n' +
              ('sys.stdout.write("x" * 100000);sys.stdout.flush()\n' if mode == 'output' else '') +
              'time.sleep(60)\n')
    worker = executable(tmp_path, source)
    monkeypatch.setattr(native_chat, 'TIMEOUT', 0.8)
    async def verify():
        task = asyncio.create_task(native_chat.run_worker(worker, b'{}', native_chat.environment()))
        async with asyncio.timeout(3):
            while not marker.exists():
                await asyncio.sleep(0.01)
        pid = int(marker.read_text())
        if mode in {'cancel', 'stubborn'}:
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(ProtocolError) as error:
                await task
            assert error.value.code == ('REQUEST_TIMEOUT' if mode == 'timeout' else 'RESPONSE_TOO_LARGE')
        assert not Path(f'/proc/{pid}').exists()
        assert not native_chat._active
    asyncio.run(verify())


@pytest.mark.skipif(not os.getenv('OMARCHY_NATIVE_CHAT_BINARY'), reason='Requires the built native Mojo worker')
def test_actual_native_broker_answers_from_mcp_without_http(native_broker, database, monkeypatch):
    assert os.getenv('OMARCHY_NATIVE_MODEL'), 'The actual supplied model must be selected explicitly'
    label = 'ORCHID-' + secrets.token_hex(3)
    row = memory.retain_memory('memory-fixture', 'Timezone fixture deployment code is ' + label,
                               'fixture:deployment', db_path=database[0])
    memory.record_memory_verification('memory-fixture', row['id'], 'fixture: simulated check', 0,
                                     'fixture:receipt', db_path=database[0])
    before = contents(database[0])
    result = native_broker(1, prompt='For this timezone fixture, what is the deployment code? Return its literal value from project memory.')
    assert result['ok'], result
    value = result['result']
    assert value['generated'] is True and label.lower() in value['answer'].lower(), value
    assert row['id'] in {item['id'] for item in value['memory']['records']}
    assert value['runtime']['backend'] == 'cpu' and value['runtime']['session_lifetime'] == 'one_request'
    assert value['runtime']['generated_tokens'] > 0
    assert contents(database[0]) == before


@pytest.mark.skipif(not os.getenv('OMARCHY_NATIVE_CHAT_BINARY'), reason='Requires the built native Mojo worker')
def test_broker_disconnect_reaps_model_worker_and_keeps_status_responsive(database, tmp_path):
    address = tmp_path / 'broker.sock'
    binary = os.getenv('OMARCHY_BROKER_BINARY', '/opt/roms-env/bin/omarchy-broker')
    process = subprocess.Popen([binary], env=dict(os.environ, OMARCHY_BROKER_SOCKET=str(address),
                               ROMS_GATEWAY_PORT='1'), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    before = contents(database[0])
    def call(frame):
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(3)
            client.connect(str(address))
            client.sendall(frame)
            return response(client)
    try:
        deadline = time.monotonic() + 10
        while not address.exists():
            assert process.poll() is None and time.monotonic() < deadline
            time.sleep(0.02)
        with socket.socket(socket.AF_UNIX) as client:
            client.connect(str(address))
            client.sendall(payload('chat', 'native-cancel', {'prompt': 'timezone', 'project_id': 'memory-fixture'}))
            deadline = time.monotonic() + 15
            model_worker = None
            while model_worker is None:
                for child in psutil.Process(process.pid).children():
                    try:
                        if child.exe() == str(Path(os.environ['OMARCHY_NATIVE_CHAT_BINARY']).resolve()):
                            model_worker = child
                    except psutil.NoSuchProcess:
                        pass
                assert time.monotonic() < deadline
                time.sleep(0.02)
            assert call(b'PING\n')['result'] == 'pong'
            deadline = time.monotonic() + 20
            while True:
                state = call(payload('status', 'native-status', {}))['result']['features']['native_project_chat']
                if state['loaded_sessions']:
                    break
                assert time.monotonic() < deadline, 'The worker never reported an actual loaded session'
                time.sleep(0.05)
            assert state['state'] == 'running' and state['active_processes'] == 1
            assert state['loaded_sessions'] == 1 and state['sessions'][0]['backend'] == 'cpu'
        deadline = time.monotonic() + 10
        while model_worker.is_running():
            assert time.monotonic() < deadline, 'Disconnected chat left a native model process'
            time.sleep(0.02)
        state = call(payload('status', 'native-idle', {}))['result']['features']['native_project_chat']
        assert state['state'] == 'idle' and state['active_processes'] == 0 and state['loaded_sessions'] == 0
        assert contents(database[0]) == before
    finally:
        process.terminate()
        process.communicate(timeout=8)


@pytest.mark.skipif(not os.getenv('OMARCHY_NATIVE_CHAT_BINARY'), reason='Requires the built native Mojo worker')
def test_native_worker_dies_when_owning_parent_is_killed(tmp_path):
    marker = tmp_path / 'child.pid'
    source = ('import os,subprocess,time,json\nfrom pathlib import Path\n'
              'from app.native_chat import environment\n'
              'p=subprocess.Popen([os.environ["OMARCHY_NATIVE_CHAT_BINARY"],str(os.getpid())],'
              'stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=environment())\n'
              f'Path({str(marker)!r}).write_text(str(p.pid))\n'
              'p.stdin.write(json.dumps({"prompt":"word "*2000,"tokens":512}).encode());p.stdin.close()\n'
              'time.sleep(60)\n')
    controller = subprocess.Popen([sys.executable, '-c', source], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not marker.exists():
            assert controller.poll() is None and time.monotonic() < deadline
            time.sleep(0.01)
        child = psutil.Process(int(marker.read_text()))
        time.sleep(0.2)
        assert child.is_running()
        controller.kill()
        controller.communicate(timeout=5)
        deadline = time.monotonic() + 8
        while child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
            assert time.monotonic() < deadline, 'Native worker survived owner death'
            time.sleep(0.02)
    finally:
        if controller.poll() is None:
            controller.kill()
            controller.communicate(timeout=5)
