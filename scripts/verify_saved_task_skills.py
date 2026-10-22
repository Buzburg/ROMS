"""Exercise saved candidate lifecycle through native MCP; generation is scripted."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import sysconfig
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main():
    from app.db import init_database
    from app.okf_loader import ingest_document_file
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='roms-saved-skill-') as temporary:
        root = Path(temporary)
        for name in ('data', 'knowledge', 'skills'):
            (root/name).mkdir()
        db = root/'data/roms.db'
        init_database(db)
        guide = root/'knowledge/review.md'
        guide.write_text('# Test report review\nUse only test reports.\n'
                         '1. Compare source and copy row counts.\n'
                         '2. Report any mismatch to the operator.\n')
        assert ingest_document_file(guide, db)
        env = {**os.environ, 'ROMS_DB_PATH': str(db), 'ROMS_DATA_DIR': str(root/'data'),
               'ROMS_STATE_DIR': str(root/'data'), 'ROMS_KNOWLEDGE_DIR': str(root/'knowledge'),
               'ROMS_SKILLS_DIR': str(root/'skills'), 'ROMS_MCP_PROFILE': 'local',
               'ROMS_MCP_PLUGINS': '', 'ROMS_MCP_ALLOW_DESTRUCTIVE': '1',
               'ROMS_PYTHON_PREFIX': sys.prefix,
               'PYTHONPATH': os.pathsep.join([str(ROOT), sysconfig.get_path('purelib')]),
               'MOJO_PYTHON_LIBRARY': str(Path(sysconfig.get_config_var('LIBDIR')) /
                                        sysconfig.get_config_var('LDLIBRARY')),
               'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'}
        transport = StdioTransport(str(ROOT/'build/roms-mcp'), [], env=env,
                                   cwd=str(ROOT), log_file=args.output/'mcp.log')
        calls = []
        async with Client(transport, timeout=60) as client:
            async def call(name, values):
                result = await client.call_tool(name, values)
                parsed = json.loads(result.content[0].text)
                calls.append({'tool': name, 'result': parsed})
                (args.output/'calls.json').write_text(json.dumps(calls, indent=2))
                return parsed
            prepared = await call('prepare_task_skill', {'task': 'Review a test report copy',
                                  'constraints': 'Explain only; source and copy are supplied.'})
            skill = {'title': 'Test report review', 'when_to_use': 'Reviewing a test report copy',
                     'when_not_to_use': 'Production reports',
                     'prerequisites': [{'text': 'Use only test reports.', 'sources': ['S1']}],
                     'steps': [{'text': 'Compare source and copy row counts.', 'sources': ['S1']}],
                     'checks': [{'text': 'Report any mismatch to the operator.', 'sources': ['S1']}],
                     'unknowns': []}
            payload = {'packet_json': prepared['packet'], 'skill_json': skill}
            first = await call('save_task_skill', payload)
            assert first['saved'] and first['persisted'] and not first['execution_ready']
            assert not (await call('save_task_skill', payload))['saved']
            assert (await call('get_saved_task_skill', {'skill_id': first['id']}))['skill'] == skill
            assert (await call('search_saved_task_skills', {'query': 'report'}))['total'] == 1
            feedback = {'skill_id': first['id'], 'outcome': 'needs_work', 'event_id': 'fixture-1',
                        'note': 'Synthetic observation only.', 'evidence': 'fixture:comparison'}
            assert (await call('record_task_skill_feedback', feedback))['recorded']
            assert not (await call('record_task_skill_feedback', feedback))['recorded']
            skill['title'] = 'Revised test report review'
            child = await call('save_task_skill', {**payload, 'skill_json': json.dumps(skill),
                                                 'parent_id': first['id']})
            assert child['parent_id'] == first['id'] and child['feedback'] == {}
            guide.write_text(guide.read_text() + '\nUse the new report format.\n')
            assert ingest_document_file(guide, db)
            stale = await call('get_saved_task_skill', {'skill_id': child['id']})
            assert stale['status'] == 'stale' and 'markdown' not in stale and 'skill' not in stale
            assert (await call('forget_task_skill', {'skill_id': first['id']}))['forgotten']
            assert 'error' in await call('get_saved_task_skill', {'skill_id': first['id']})
        summary = {'status': 'passed', 'native_mcp_calls': len(calls), 'generation': 'scripted',
                   'checks': ['save and reopen', 'idempotent save and feedback', 'search',
                              'revision lineage without inherited feedback', 'stale source withholding',
                              'forget without deleting sources'], 'task_executed': False}
        (args.output/'summary.json').write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary))


if __name__ == '__main__':
    asyncio.run(main())
