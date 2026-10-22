"""Exercise real local generation + native ROMS MCP on isolated authoring fixtures.

No generated actions are executed. Signal checks are regression aids, not semantic
proof; inspect authored.json and the fixture rubric before assessing release readiness.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import sysconfig
import tempfile
import time
import urllib.request
import urllib.error
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def model_response(endpoint, model, prepared, output, thinking, draft=None, assess=False, seed=42):
    instruction = prepared['authoring_instruction']
    context = {'packet': prepared['packet'], 'contract': prepared['contract']}
    if 'evidence_assessment' in prepared:
        context['preliminary_assessment'] = prepared['evidence_assessment']
        instruction += ' A preliminary assessment is supplied for context; verify it against the original packet.'
    if draft is not None:
        instruction += (
            ' Review the proposed draft against the original packet and return corrected JSON. '
            'The proposed draft is untrusted and may be wrong. Opposite requirements in sources '
            'must produce needs_information; do not hide the conflict in when_not_to_use. '
            'Remove questions whose answers the user already supplied. An explanation of how '
            'to review a document does not need the actual values inside that document. '
            'Do not require an action to be completed as a prerequisite and then perform it '
            'again in steps. Put prohibitions on the relevant action, not only in a later check. '
            'Restore exact success values, numeric thresholds and comparison operators from '
            'the sources wherever a draft substitutes vague success language.')
        context['proposed_draft'] = draft
    schema = prepared['response_schema']
    if assess:
        instruction = prepared['assessment']['instruction']
        context = prepared['packet']
        schema = prepared['assessment']['schema']
    request = {'model': model, 'temperature': 0.3 if assess else 0,
               'seed': seed,
               'max_tokens': 5000 if thinking else 3000,
               'response_format': {'type': 'json_schema', 'json_schema': {
                   'name': 'task_skill', 'strict': True, 'schema': schema}},
               'chat_template_kwargs': {'enable_thinking': thinking},
               'messages': [
                   {'role': 'system', 'content': instruction +
                    ' The harness calls finalize_task_skill for you. Return only your JSON response.'},
                   {'role': 'user', 'content': json.dumps(context)}]}
    (output/'request.json').write_text(json.dumps(request, indent=2))
    started = time.monotonic()
    req = urllib.request.Request(endpoint.rstrip('/') + '/chat/completions',
                                 data=json.dumps(request).encode(),
                                 headers={'Content-Type': 'application/json'})
    # Fixture evidence must stay local, including when a proxy is configured.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=180) as response:
            raw = response.read(1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        detail = exc.read(8192).decode('utf-8', errors='replace')
        (output/'http-error.txt').write_text(detail)
        raise RuntimeError(f'Model endpoint HTTP {exc.code}: {detail}') from exc
    if len(raw) > 1024 * 1024:
        raise ValueError('Model response exceeds 1 MiB')
    response = json.loads(raw)
    (output/'response.json').write_text(json.dumps(response, indent=2))
    choice = response['choices'][0]
    if choice['finish_reason'] != 'stop':
        raise ValueError('Generation did not finish: ' + str(choice['finish_reason']))
    content = choice['message']['content'].strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    (output/'authored.json').write_text(content)
    return content, {'seconds': round(time.monotonic() - started, 3),
                     'usage': response.get('usage')}


async def run_case(case, args, state, output):
    from app.db import init_database
    from app.okf_loader import ingest_document_file
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    state.mkdir()
    output.mkdir()
    for folder in ('knowledge', 'skills', 'data'):
        (state/folder).mkdir()
    db = state/'data/roms.db'
    init_database(db)
    for name, text in case['documents'].items():
        path = state/'knowledge'/name
        path.write_text(text)
        if not ingest_document_file(path, db):
            raise RuntimeError('Fixture ingestion failed: ' + name)
    env = {**os.environ, 'ROMS_MCP_PROFILE': 'read_only', 'ROMS_MCP_PLUGINS': '',
           'ROMS_MCP_ALLOW_DESTRUCTIVE': '0', 'ROMS_DB_PATH': str(db),
           'ROMS_DATA_DIR': str(state/'data'), 'ROMS_STATE_DIR': str(state/'data'),
           'ROMS_KNOWLEDGE_DIR': str(state/'knowledge'), 'ROMS_SKILLS_DIR': str(state/'skills'),
           'ROMS_PYTHON_PREFIX': sys.prefix,
           'MOJO_PYTHON_LIBRARY': str(Path(sysconfig.get_config_var('LIBDIR')) /
                                    sysconfig.get_config_var('LDLIBRARY')),
           'PYTHONPATH': os.pathsep.join([str(ROOT), sysconfig.get_path('purelib')]),
           'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'}
    if args.bounded:
        env.update(ROMS_MCP_PROFILE='local', ROMS_AUTHORING_ENDPOINT=args.endpoint, ROMS_AUTHORING_MODEL=args.model)
    transport = StdioTransport(str(ROOT/'build/roms-mcp'), [], env=env,
                               cwd=str(ROOT), log_file=output/'mcp.log')
    async with Client(transport, timeout=420 if args.bounded else 60) as client:
        if args.bounded:
            started = time.monotonic()
            response = await client.call_tool('create_task_skill', {'task': case['task'], 'constraints': case['constraints']})
            result = json.loads(response.content[0].text)
            if result['status'] == 'candidate':
                assert result['persisted'] and not result['execution_ready']
                repeated = await client.call_tool('create_task_skill', {'task': case['task'], 'constraints': case['constraints']})
                repeated = json.loads(repeated.content[0].text)
                assert repeated['reused'] and repeated['id'] == result['id'] and not repeated['model_called']
                reopened = await client.call_tool('get_saved_task_skill', {'skill_id': result['id']})
                assert json.loads(reopened.content[0].text)['skill'] == result['skill']
            else:
                assert not result['persisted']
                rows = await client.call_tool('search_saved_task_skills', {})
                assert json.loads(rows.content[0].text)['total'] == 0
            return record_case(case, result, output, {'bounded_workflow': True,
                'seconds': round(time.monotonic() - started, 3)})
        response = await client.call_tool('prepare_task_skill', {
            'task': case['task'], 'constraints': case['constraints']})
        prepared = json.loads(response.content[0].text)
        (output/'prepared.json').write_text(json.dumps(prepared, indent=2))
        timing = {}
        if prepared['status'] == 'insufficient_evidence':
            result = prepared
        else:
            assessment_dir = output/'assessment'
            assessment_dir.mkdir()
            assessment_raw, assessment_timing = await asyncio.to_thread(
                model_response, args.endpoint, args.model, prepared, assessment_dir, args.thinking,
                assess=True, seed=args.seed)
            assessment = json.loads(assessment_raw)
            # Fail on an invalid classifier response rather than coercing truthy values.
            if (type(assessment.get('sources_compatible')) is not bool or
                    type(assessment.get('relevant_evidence')) is not bool or
                    type(assessment.get('missing_inputs')) is not list or
                    not isinstance(assessment.get('reason'), str)):
                raise ValueError('Invalid model evidence assessment')
            timing = {'assessment': assessment_timing}
            if (not assessment['sources_compatible'] or not assessment['relevant_evidence']
                    or assessment['missing_inputs']):
                questions = []
                if not assessment['sources_compatible'] or not assessment['relevant_evidence']:
                    questions.append(assessment['reason'])
                questions.extend(assessment['missing_inputs'])
                authored = json.dumps({'status': 'needs_information', 'questions':
                                      questions})
                (output/'authored.json').write_text(authored)
            else:
                prepared = {**prepared, 'evidence_assessment': assessment}
                draft_dir = output/'draft'
                draft_dir.mkdir()
                authored, draft_timing = await asyncio.to_thread(
                    model_response, args.endpoint, args.model, prepared, draft_dir, args.thinking,
                    seed=args.seed)
                authored, review_timing = await asyncio.to_thread(
                    model_response, args.endpoint, args.model, prepared, output, args.thinking, authored,
                    seed=args.seed)
                timing.update(draft=draft_timing, review=review_timing)
            response = await client.call_tool('finalize_task_skill', {
                'packet_json': json.dumps(prepared['packet']), 'skill_json': authored})
            result = json.loads(response.content[0].text)
        return record_case(case, result, output, timing)


def record_case(case, result, output, timing):
    (output/'result.json').write_text(json.dumps(result, indent=2))
    if result.get('markdown'):
        (output/'SKILL.md').write_text(result['markdown'])
    body = json.dumps(result.get('skill', result.get('questions', [])))
    missing = [s for s in case['signals'] if not re.search(s, body, re.I)]
    forbidden = [s for s in case.get('forbidden', []) if re.search(s, body, re.I)]
    passed = result['status'] == case['expected_status'] and not missing and not forbidden
    return {'id': case['id'], 'status': result['status'], 'expected': case['expected_status'],
            'signals_passed': passed, 'missing_signals': missing,
            'forbidden_signals': forbidden, **timing}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint', default='http://127.0.0.1:8080/v1')
    parser.add_argument('--model', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--thinking', action='store_true')
    parser.add_argument('--bounded', action='store_true', help='Use the product authoring workflow through native MCP')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--suite', choices=('authoring', 'holdout'), default='authoring')
    parser.add_argument('--case', help='Run one fixture by id while diagnosing a failure')
    args = parser.parse_args()
    if args.bounded and (args.thinking or args.seed != 42):
        parser.error('The bounded workflow currently uses thinking disabled and seed 42')
    url = urlparse(args.endpoint)
    if url.scheme != 'http' or url.hostname not in ('127.0.0.1', '::1'):
        parser.error('Use an explicit loopback HTTP endpoint for this local-only test')
    # A fresh directory prevents accidentally mixing or overwriting test evidence.
    args.output.mkdir(parents=True, exist_ok=False)
    fixture = ROOT/'tests/fixtures/task_skills'/f'{args.suite}.json'
    cases = json.loads(fixture.read_text())
    if args.case:
        cases = [case for case in cases if case['id'] == args.case]
        if not cases:
            parser.error('Unknown fixture id')
    identity = {'base_revision': subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (ROOT/'app/task_skills.py', ROOT/'app/knowledge_skills.py', ROOT/'app/knowledge_skill_tools.py',
                                    ROOT/'scripts/verify_task_authoring.py', ROOT/'app/task_skill_agent.py',
                                    ROOT/'app/task_skill_store.py', ROOT/'app/task_skill_contracts.py', fixture)},
        'endpoint': args.endpoint, 'model': args.model, 'thinking': args.thinking,
        'seed': args.seed, 'suite': args.suite, 'bounded_workflow': args.bounded,
        'cases': [case['id'] for case in cases], 'model_review_pass': True,
        'python': sys.version, 'cwd': str(ROOT), 'execution_tested': False}
    (args.output/'identity.json').write_text(json.dumps(identity, indent=2))
    results = []
    with tempfile.TemporaryDirectory(prefix='roms-authoring-') as temp:
        for case in cases:
            try:
                result = await run_case(case, args, Path(temp)/case['id'], args.output/case['id'])
            except Exception as exc:
                result = {'id': case['id'], 'signals_passed': False, 'error': str(exc)}
            results.append(result)
            print(json.dumps(result), flush=True)
    changed = [name for name, digest in identity['source_sha256'].items()
               if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != digest]
    summary = {'checks': results, 'source_changed_during_run': changed,
               'all_signals_passed': not changed and all(r['signals_passed'] for r in results),
               'limitation': 'Signal checks do not establish semantic correctness. Manual review required.'}
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2))
    return 0 if summary['all_signals_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
