"""Turn selected project files and an operator request into an untrusted staged draft."""
import asyncio
import json
import os
from pathlib import Path
import uuid

import httpx

from app import patch_tasks as tasks
from app.container_runner import run_process
from app.git_workspace import safe_git
from app.json_protocol import unique_object
from app.project_contract import validate_payload


async def generate(instruction: str, snapshots: dict[str, str | None]) -> dict:
    key = os.getenv('ROMS_GATEWAY_API_KEY')
    if not key:
        raise RuntimeError('Use the installed ROMS launcher to access the local model')
    body = {'instruction': instruction, 'files': snapshots}
    validate_payload(body)
    port = int(os.getenv('ROMS_GATEWAY_PORT', '8844'))
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        async with asyncio.timeout(90):
            while True:
                try:
                    health = await client.get(f'http://127.0.0.1:{port}/health',
                        headers={'Authorization': 'Bearer ' + key}, timeout=3)
                    health.raise_for_status()
                    status = health.json()
                    if status.get('upstream_ready') and status.get('status') == 'ready':
                        break
                except (httpx.ConnectError, httpx.ReadTimeout):
                    pass
                await asyncio.sleep(1)
        async with client.stream('POST', f'http://127.0.0.1:{port}/v1/project/draft', json=body,
                                 headers={'Authorization': 'Bearer ' + key}) as response:
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 65536:
                    raise ValueError('Model response exceeds the local draft limit')
    return json.loads(data.decode('utf-8'), object_pairs_hook=unique_object)


def parse_changes(response: dict, snapshots: dict[str, str | None]) -> list[dict]:
    choice = response['choices'][0]
    if choice['finish_reason'] != 'stop':
        raise ValueError('Model output was incomplete; no patch was staged')
    text = choice['message']['content']
    if not isinstance(text, str) or len(text.encode('utf-8')) > 16384:
        raise ValueError('Expected bounded JSON model output')
    value = json.loads(text, object_pairs_hook=unique_object)
    if (type(value) is not dict or set(value) != {'changes'} or type(value['changes']) is not list
            or not 1 <= len(value['changes']) <= len(snapshots)):
        raise ValueError('Model output must contain a bounded changes array')
    changes, seen = [], set()
    for entry in value['changes']:
        if type(entry) is not dict or set(entry) != {'path', 'after'} or type(entry['path']) is not str:
            raise ValueError('Each model change must contain only path and after')
        name, after = entry['path'], entry['after']
        if name not in snapshots or name in seen:
            raise ValueError('Model selected an unapproved or duplicate path')
        if after is not None and (type(after) is not str or '\x00' in after):
            raise ValueError('Model replacement must be UTF-8 text or null')
        seen.add(name)
        before = snapshots[name]
        # Preserve the existing file's final line terminator without collapsing blank lines.
        if before and after and before.endswith('\n'):
            ending = '\r\n' if before.endswith('\r\n') else '\n'
            if after.endswith('\r\n'):
                after = after[:-2] + ending
            elif after.endswith('\n'):
                after = after[:-1] + ending
            else:
                after += ending
        if after == before:
            continue
        changes.append({'path': name, 'before_sha256': None if before is None else tasks.sha(before.encode('utf-8')),
                        'after': after})
    if not changes:
        raise ValueError('Model proposed no changes')
    return changes


async def draft_change(project_id: str, files: list[str], instruction: str, checks: list[dict]) -> dict:
    if (type(files) is not list or not 1 <= len(files) <= 4 or len(set(files)) != len(files)
            or not isinstance(instruction, str) or not instruction.strip() or len(instruction.encode('utf-8')) > 1024):
        raise ValueError('Select 1–4 files and provide a change request up to 1024 bytes')
    for name in files:
        tasks.patch_path(name)
    project = json.loads((tasks.STORE / 'projects' / (tasks.identifier(project_id) + '.json')).read_text())
    source = Path(project['source'])
    info = source.stat()
    if [info.st_dev, info.st_ino] != [project.get('device'), project.get('inode')]:
        raise ValueError('Registered project directory changed')
    git = await safe_git(source)
    revision = await run_process([*git, 'rev-parse', 'HEAD'], 10)
    if revision.returncode:
        raise ValueError('Cannot read the registered project revision')
    base = revision.output.strip()
    snapshots = {}
    for name in files:
        before = tasks.read_file(source, name)
        if before is not None and b'\x00' in before:
            raise ValueError('Select UTF-8 text files, not binary content')
        snapshots[name] = None if before is None else before.decode('utf-8')
    validate_payload({'instruction': instruction, 'files': snapshots})
    directory = tasks.STORE / 'drafts' / uuid.uuid4().hex
    directory.mkdir(parents=True, mode=0o700)
    record = {'id': directory.name, 'state': 'generating', 'project_id': project_id, 'base_commit': base,
              'instruction': instruction, 'files': files, 'checks': checks,
              'input_sha256': tasks.sha(tasks.canonical(snapshots))}
    tasks.durable_json(directory / 'draft.json', record)
    try:
        response = await generate(instruction, snapshots)
        tasks.durable_json(directory / 'response.json', response)
        changes = parse_changes(response, snapshots)
        current = await run_process([*git, 'rev-parse', 'HEAD'], 10)
        if current.returncode or current.output.strip() != base:
            raise ValueError('Project revision changed while the model was drafting')
        for name, before in snapshots.items():
            actual = tasks.read_file(source, name)
            if actual != (None if before is None else before.encode('utf-8')):
                raise ValueError('Selected file changed while the model was drafting: ' + name)
        task = await tasks.propose(project_id, base, changes, checks)
        record.update(state='staged', task_id=task['id'], patch_sha256=task['patch_sha256'],
                      model=response.get('model'), usage=response.get('usage'),
                      formatting_policy='preserve-existing-final-newline')
        tasks.durable_json(directory / 'draft.json', record)
        return {'draft_id': directory.name, 'task': task}
    except BaseException as error:
        record.update(state='failed', error=type(error).__name__ + ': ' + str(error)[:512])
        tasks.durable_json(directory / 'draft.json', record)
        raise
