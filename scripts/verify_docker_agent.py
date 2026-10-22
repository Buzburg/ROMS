"""Real Docker Agent + ROMS MCP transport test with scripted model responses.

Requires an explicitly supplied standalone Docker Agent binary and built ROMS MCP.
No real generation model is used; this does not measure autonomous task quality.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    binary = args.agent.resolve(strict=True)
    native = (ROOT / 'build/roms-mcp').resolve(strict=True)
    args.output.mkdir(parents=True, exist_ok=True)
    import yaml
    from app.db import init_database
    from app.okf_loader import ingest_document_file
    from app.knowledge_skills import list_drafts, get_draft
    with tempfile.TemporaryDirectory(prefix='roms-agent-trial-') as temp:
        state = Path(temp)
        for folder in ('data', 'knowledge', 'skills', 'agent'):
            (state / folder).mkdir()
        db = state / 'data/roms.db'
        init_database(db)
        guide = state / 'knowledge/staging.md'
        guide.write_text('# Staging backup\n\nUse only on a disposable staging database.\n\n1. Stop the staging writer.\n2. Copy the database to a new backup file.\n3. Verify the copy opens.\n')
        assert ingest_document_file(guide, db)
        draft = get_draft(list_drafts(db)['skills'][0]['id'], db)
        results = []
        for profile in ('read_only', 'local'):
            requests = []
            calls = [
                ('search_knowledge_skills', {'query': 'staging backup'}),
                ('get_knowledge_skill', {'skill_id': draft['id']}),
                ('record_knowledge_skill_feedback', {'skill_id': draft['id'], 'revision': draft['revision'],
                    'outcome': 'helpful', 'event_id': 'scripted-' + profile,
                    'note': 'Synthetic transport fixture only; no backup was executed.'}),
                ('prepare_task_skill', {'task': 'Back up the staging database', 'constraints': 'Keep production untouched'}),
                ('finalize_task_skill', {}),
                ('save_task_skill', {}),
                ('search_saved_task_skills', {'query': 'staging'}),
                ('get_saved_task_skill', {}),
                ('record_task_skill_feedback', {}),
            ]
            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *_):
                    pass

                def do_POST(self):
                    body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    requests.append(body)
                    tool_messages = [m for m in body['messages'] if m['role'] == 'tool']
                    index = len(tool_messages)
                    if index < len(calls):
                        name, parameters = calls[index]
                        if name == 'finalize_task_skill':
                            prepared = json.loads(tool_messages[-1]['content'])
                            authored = {'title': 'Staging-only backup', 'when_to_use': 'A staging backup is needed',
                                'when_not_to_use': 'Production or an unidentified database',
                                'prerequisites': [{'text': 'Confirm the disposable staging database.', 'sources': ['S1']}],
                                'steps': [{'text': 'Stop the staging writer, then copy the database to a new file.', 'sources': ['S1']}],
                                'checks': [{'text': 'Verify that the copy opens.', 'sources': ['S1']}],
                                'unknowns': []}  # Scripted transport contract, not an execution-ready plan.
                            parameters = {'packet_json': json.dumps(prepared['packet']), 'skill_json': json.dumps(authored)}
                        if name == 'save_task_skill':
                            parameters = json.loads(next(m for m in body['messages']
                                if m.get('tool_calls') and m['tool_calls'][0]['id'] == 'call_4')
                                ['tool_calls'][0]['function']['arguments'])
                        elif name in ('get_saved_task_skill', 'record_task_skill_feedback'):
                            candidate = json.loads(tool_messages[4]['content'])
                            parameters = {'skill_id': candidate['id']}
                            if name == 'record_task_skill_feedback':
                                parameters.update(outcome='needs_work', event_id='candidate-' + profile,
                                    note='Synthetic observation: task was not executed.', evidence='transport-fixture')
                        # Resolve the real advertised name; MCP clients may namespace it.
                        names = [t['function']['name'] for t in body.get('tools', [])]
                        matches = [n for n in names if n == name or n.endswith('_' + name)]
                        if len(matches) != 1:
                            self.send_error(500, 'Expected ROMS tool missing')
                            return
                        delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': f'call_{index}',
                                 'type': 'function', 'function': {'name': matches[0], 'arguments': json.dumps(parameters)}}]}
                        finish = 'tool_calls'
                    else:
                        delta = {'role': 'assistant', 'content': 'Scripted transport fixture complete. No task execution or model reasoning was tested.'}
                        finish = 'stop'
                    base = {'id': 'fixture', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'fixture'}
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.end_headers()
                    for change, reason in ((delta, None), ({}, finish)):
                        packet = dict(base, choices=[{'index': 0, 'delta': change, 'finish_reason': reason}])
                        self.wfile.write(('data: ' + json.dumps(packet) + '\n\n').encode())
                    self.wfile.write(b'data: [DONE]\n\n')
                    self.wfile.flush()

            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            env = {**os.environ, 'TELEMETRY_ENABLED': 'false', 'DOCKER_AGENT_AUTO_INSTALL': 'false',
                   'DOCKER_AGENT_DATA_DIR': str(state / 'agent'), 'OPENAI_API_KEY': 'fixture-not-a-secret',
                   'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
                   'PYTHONPATH': os.pathsep.join([str(ROOT), sysconfig.get_path('purelib')]),
                   'ROMS_PYTHON_PREFIX': sys.prefix,
                   'MOJO_PYTHON_LIBRARY': str(Path(sysconfig.get_config_var('LIBDIR')) / sysconfig.get_config_var('LDLIBRARY'))}
            mcp_env = {key: env[key] for key in ('PYTHONPATH', 'ROMS_PYTHON_PREFIX', 'MOJO_PYTHON_LIBRARY', 'HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE')}
            mcp_env.update(ROMS_MCP_PROFILE=profile, ROMS_MCP_ALLOW_DESTRUCTIVE='0', ROMS_DB_PATH=str(db),
                           ROMS_DATA_DIR=str(state/'data'), ROMS_STATE_DIR=str(state/'data'),
                           ROMS_KNOWLEDGE_DIR=str(state/'knowledge'), ROMS_SKILLS_DIR=str(state/'skills'))
            template = ROOT / 'examples/docker-agent' / ('roms-retain.yaml' if profile == 'local' else 'roms.yaml')
            config = yaml.safe_load(template.read_text())
            config['models'] = {'fixture': {'provider': 'openai', 'model': 'fixture',
                'base_url': f'http://127.0.0.1:{server.server_port}/v1'}}
            root = config['agents']['root']
            root['model'] = 'fixture'
            toolset = root['toolsets'][0]
            if profile == 'local':
                assert all(name in toolset['tools'] for name, _ in calls)
                assert toolset['env']['ROMS_MCP_PROFILE'] == 'local'
                assert toolset['env']['ROMS_MCP_ALLOW_DESTRUCTIVE'] == '0'
            else:
                # Advertise writes deliberately to verify server-side read-only denial.
                toolset['tools'] = [name for name, _ in calls]
            toolset.update(command=str(native), working_dir=str(ROOT), env=mcp_env)
            config_path = state / f'{profile}.yaml'
            config_path.write_text(yaml.safe_dump(config))
            try:
                # Only these ROMS fixture tools are exposed, against a throwaway database.
                process = subprocess.run([str(binary), 'run', str(config_path), '--exec', '--safety', 'autonomous',
                    'Run the scripted synthetic transport check.'], env=env, cwd=state,
                    capture_output=True, text=True, timeout=90)
            finally:
                server.shutdown()
                server.server_close()
                worker.join()
            (args.output / f'{profile}.log').write_text(process.stdout + '\n' + process.stderr)
            (args.output / f'{profile}-requests.json').write_text(json.dumps(requests, indent=2))
            assert process.returncode == 0, f'{profile}: exit {process.returncode}; inspect log'
            observed = [m for m in requests[-1]['messages'] if m['role'] == 'tool'] if requests else []
            assert len(observed) == len(calls), f'{profile}: expected {len(calls)} real MCP results'
            authored_result = json.loads(observed[4]['content'])
            assert authored_result['status'] == 'candidate' and not authored_result['persisted']
            assert 'Staging-only backup' in authored_result['markdown']
            assert draft['id'] in str(observed[0]), 'Skill search did not return seeded skill'
            assert draft['revision'] in str(observed[1]), 'Skill detail did not return source revision'
            current = get_draft(draft['id'], db)
            if profile == 'read_only':
                assert 'read_only' in str(observed[2]), 'Write was not denied by ROMS policy'
                assert current['feedback'] == {}, 'Read-only attempt changed feedback'
            else:
                assert current['feedback'] == {'helpful': 1}, 'Local feedback did not persist'
                assert current['observations'][0]['note'].startswith('Synthetic transport fixture')
            from app import task_skill_store as saved
            saved_result = json.loads(observed[6]['content'])
            if profile == 'read_only':
                assert 'read_only' in str(observed[5]) and 'read_only' in str(observed[8])
                assert saved_result['total'] == 0 and saved.search(db_path=db)['total'] == 0
            else:
                assert json.loads(observed[5]['content'])['persisted']
                assert saved_result['total'] == 1
                reopened = json.loads(observed[7]['content'])
                assert reopened['id'] == authored_result['id'] and not reopened['execution_ready']
                assert saved.get(reopened['id'], db)['feedback'] == {'needs_work': 1}
            results.append({'profile': profile, 'mcp_results': len(observed), 'status': 'passed'})
        summary = {'status': 'passed', 'generation': 'scripted fixture, not a real model', 'checks': results}
        (args.output/'result.json').write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary))


if __name__ == '__main__':
    main()
