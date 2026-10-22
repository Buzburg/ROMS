"""Exercise the retaining Docker Agent example with a real loopback model.

The model chooses tools. Only ROMS tools and disposable source data are exposed;
no generated procedure is executed. A saved candidate is inspected independently.
"""
import argparse
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent', type=Path, required=True)
    parser.add_argument('--endpoint', default='http://127.0.0.1:18973/v1')
    parser.add_argument('--model', required=True)
    parser.add_argument('--template', choices=('retain', 'agent'), default='retain')
    parser.add_argument('--scenario', choices=('revision', 'conflict', 'task', 'all'), default='revision')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed-candidate', type=Path, help='Replay one prior generated candidate against the exact fixture; skip regeneration')
    args = parser.parse_args()
    if args.scenario == 'task' and args.seed_candidate:
        parser.error('The task scenario must create its own candidate')
    endpoint = urlparse(args.endpoint)
    if endpoint.scheme != 'http' or endpoint.hostname not in ('127.0.0.1', '::1', 'localhost'):
        parser.error('Use an HTTP loopback endpoint for this local fixture')
    binary = args.agent.resolve(strict=True)
    args.output.mkdir(parents=True, exist_ok=False)
    import yaml
    from app.db import init_database
    from app.okf_loader import ingest_document_file
    from app import task_skill_store as saved
    with tempfile.TemporaryDirectory(prefix='roms-real-agent-') as temp:
        state = Path(temp)
        for name in ('data', 'knowledge', 'skills', 'agent'):
            (state/name).mkdir()
        db = state/'data/roms.db'
        init_database(db)
        guide = state/'knowledge/report.md'
        guide.write_text('# Report review\n\nThis procedure reviews a supplied report without modifying files.\n\n'
                         '1. Read the supplied report.\n2. List each missing required field: title, date, author.\n'
                         '3. Return PASS only if all three required fields are present; otherwise return FAIL and list missing fields.\n')
        assert ingest_document_file(guide, db)
        config = yaml.safe_load((ROOT/'examples/docker-agent'/f'roms-{args.template}.yaml').read_text())
        config['models'] = {'local': {'provider': 'openai', 'model': args.model,
            'base_url': args.endpoint, 'temperature': 0, 'max_tokens': 4096}}
        root = config['agents']['root']
        root['max_iterations'] = 12
        runtime = {'PYTHONPATH': os.pathsep.join([str(ROOT), sysconfig.get_path('purelib')]),
            'ROMS_PYTHON_PREFIX': sys.prefix,
            'MOJO_PYTHON_LIBRARY': str(Path(sysconfig.get_config_var('LIBDIR'))/sysconfig.get_config_var('LDLIBRARY')),
            'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'}
        toolset = root['toolsets'][0]
        toolset.update(command=str(ROOT/'build/roms-mcp'), working_dir=str(ROOT),
            env={**runtime, 'ROMS_AUTHORING_ENDPOINT': args.endpoint, 'ROMS_AUTHORING_MODEL': args.model,
                 'ROMS_MCP_PROFILE': 'local', 'ROMS_MCP_ALLOW_DESTRUCTIVE': '0',
                 'ROMS_DB_PATH': str(db), 'ROMS_DATA_DIR': str(state/'data'), 'ROMS_STATE_DIR': str(state/'data'),
                 'ROMS_KNOWLEDGE_DIR': str(state/'knowledge'), 'ROMS_SKILLS_DIR': str(state/'skills')})
        config_path = state/'agent.yaml'
        config_path.write_text(yaml.safe_dump(config))
        env = {**os.environ, **runtime, 'TELEMETRY_ENABLED': 'false', 'DOCKER_AGENT_AUTO_INSTALL': 'false',
            'DOCKER_AGENT_DATA_DIR': str(state/'agent'), 'OPENAI_API_KEY': 'local-fixture'}
        prompt = ('Create and retain a reusable skill for reviewing a supplied report using ROMS knowledge. '
                  'This is preparation only: do not perform the review or report a successful task outcome. '
                  'The future report is an input at use time. Do not modify report files.')
        if args.scenario in ('task', 'all'):
            prompt = ('Outline the report review procedure for my team using our indexed guidance. '
                      'This is preparation only; do not review a report or edit report files.')
        (args.output/'prompt.txt').write_text(prompt)
        def run_agent(request, log_name):
            with (args.output/log_name).open('w') as transcript:
                process = subprocess.Popen([str(binary), 'run', str(config_path), '--exec', '--safety', 'autonomous', request],
                    cwd=state, env=env, stdout=transcript, stderr=subprocess.STDOUT,
                    start_new_session=True)
                try:
                    returncode = process.wait(timeout=240)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    returncode = 'timeout'
            return returncode
        if args.seed_candidate:
            from app.task_skills import prepare
            previous = json.loads(args.seed_candidate.read_text())
            if len(previous) != 1:
                raise ValueError('Expected exactly one prior candidate')
            previous = previous[0]
            packet = prepare(previous['task'], previous['constraints'], db)['packet']
            restored = saved.save(json.dumps(packet), json.dumps(previous['skill']), db_path=db)
            assert restored['id'] == previous['id'], 'Seed differs from the original fixture'
            returncode = 0
        else:
            returncode = run_agent(prompt, 'agent.log')
        candidates = saved.search(db_path=db)
        details = [saved.get(item['id'], db) for item in candidates['skills']]
        (args.output/'candidates.json').write_text(json.dumps(details, indent=2))
        checks = {'process_completed': returncode == 0, 'candidate_saved': bool(details),
                  'all_current': bool(details) and all(d['status'] == 'candidate' for d in details),
                  'no_feedback_invented': all(not d.get('feedback') for d in details),
                  'no_execution_certification': all(not d['execution_ready'] for d in details)}
        if all(checks.values()):
            reuse_prompt = ('Find the saved report-review skill and explain its required fields and PASS/FAIL rule. '
                            'Use the existing candidate. Do not create or revise a skill, execute the procedure, '
                            'or record outcome feedback.')
            (args.output/'reuse-prompt.txt').write_text(reuse_prompt)
            reuse_code = run_agent(reuse_prompt, 'reuse.log')
            reuse_log = (args.output/'reuse.log').read_text()
            after = saved.search(db_path=db)
            checks.update(reuse_completed=reuse_code == 0,
                reuse_read_tool_called='Calling get_saved_task_skill(' in reuse_log,
                reuse_identifies_saved_candidate=any(d['id'] in reuse_log for d in details),
                reuse_no_duplicate=after['total'] == candidates['total'],
                reuse_no_feedback=all(not saved.get(d['id'], db)['feedback'] for d in details))
        if all(checks.values()) and args.scenario in ('revision', 'all'):
            parent = details[0]
            saved.record_feedback(parent['id'], 'needs_work', 'fixture-change-request',
                'Synthetic change-request observation; no report review executed.',
                'fixture:requirements-update', db)
            guide.write_text('# Report review\n\nThis procedure reviews a supplied report without modifying files.\n\n'
                '1. Read the supplied report.\n'
                '2. List each missing required field: title, date, author, reviewer. Treat a blank field as missing.\n'
                '3. Return PASS only if all four required fields are present and nonblank; otherwise return FAIL and list missing fields.\n')
            assert ingest_document_file(guide, db)
            stale = saved.get(parent['id'], db)
            checks['old_body_withheld'] = stale['status'] == 'stale' and 'skill' not in stale and 'markdown' not in stale
            revision_prompt = ('The indexed report-review requirements have changed. Revise the saved report-review '
                'skill using the current source, retaining its original constraints and linking the new candidate '
                'to its parent. Do not execute a review or report a task outcome.')
            (args.output/'revision-prompt.txt').write_text(revision_prompt)
            revision_code = run_agent(revision_prompt, 'revision.log')
            revised = [saved.get(row['id'], db) for row in saved.search(db_path=db)['skills']]
            (args.output/'revisions.json').write_text(json.dumps(revised, indent=2))
            children = [d for d in revised if d.get('parent_id') == parent['id'] and d['status'] == 'candidate']
            checks.update(revision_completed=revision_code == 0, revision_linked=len(children) == 1)
            if children:
                child = children[0]
                body = json.dumps(child['skill']).lower()
                checks.update(new_requirements_mentioned='reviewer' in body and 'blank' in body,
                    revision_feedback_isolated=not child['feedback'],
                    revision_remains_candidate=not child['execution_ready'],
                    original_constraints_preserved=child['constraints'] == parent['constraints'])
        if all(checks.values()) and args.scenario in ('conflict', 'all'):
            count_before_conflict = saved.search(db_path=db)['total']
            conflict = state/'knowledge/conflict.md'
            conflict.write_text('# Report review requirements\n\nFor every supplied report review, '
                'the presence of an author field requires FAIL, even when title and date are present. '
                'Never return PASS for a report containing an author field.\n')
            assert ingest_document_file(conflict, db)
            conflict_prompt = ('Revise the saved report-review skill using all current indexed requirements. '
                'No source has precedence over another. Identify unresolved issues before saving. '
                'Do not execute a review or record an outcome.')
            (args.output/'conflict-prompt.txt').write_text(conflict_prompt)
            conflict_code = run_agent(conflict_prompt, 'conflict.log')
            conflict_log = (args.output/'conflict.log').read_text()
            checks.update(conflict_completed=conflict_code == 0,
                conflicting_sources_retrieved='conflict.md' in conflict_log and 'report.md' in conflict_log,
                conflict_no_candidate_saved=saved.search(db_path=db)['total'] == count_before_conflict)
            # Final questions and their correctness require transcript review. A marker
            # in the prepare schema is not evidence of an actual abstention response.
        summary = {'status': 'passed' if all(checks.values()) else 'failed', 'checks': checks,
                   'returncode': returncode, 'generation': 'real model; autonomous tool selection',
                   'model': args.model, 'task_executed': False,
                   'scenario': args.scenario, 'template': args.template,
                   'creation': 'replayed prior generated candidate' if args.seed_candidate else 'real generation',
                   'scope': 'Workflow acceptance only; manually review candidate entailment and transcript.'}
        (args.output/'summary.json').write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary))
        if summary['status'] != 'passed':
            raise SystemExit(1)


if __name__ == '__main__':
    main()
