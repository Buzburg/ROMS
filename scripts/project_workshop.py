"""Guided local project edits: describe, draft, validate, review and approve."""
import asyncio
import json
from pathlib import Path

import httpx

from app import patch_tasks, patch_promotion, project_assistant, project_repair, task_worker_client
from app.workbench.context import CodeIndex, compact_log
from app.workbench.integrations import review_task
from app.workbench.receipts import Collector


def display(value: str) -> None:
    for line in value.splitlines():
        print(json.dumps(line, ensure_ascii=True)[1:-1])


async def select_project() -> dict:
    projects = [json.loads(path.read_text()) for path in sorted((patch_tasks.STORE / 'projects').glob('*.json'))[:100]]
    for number, project in enumerate(projects, 1):
        print(f'{number}. ' + json.dumps(project['source']))
    print('0. Add an existing local repository')
    selected = input('Project number (Enter returns): ').strip()
    if not selected or selected == '/exit':
        raise EOFError
    if selected == '0':
        return await patch_tasks.register_project(input('Repository folder: ').strip())
    if not selected.isdecimal() or not 1 <= int(selected) <= len(projects):
        raise ValueError('Choose one of the listed project numbers')
    return projects[int(selected) - 1]


def select_files(project: dict) -> tuple[list[str], list[dict]]:
    files = [value.strip() for value in input('Files to edit (1–4 relative paths, separated by commas): ').split(',')]
    if not 1 <= len(files) <= 4 or len(set(files)) != len(files):
        raise ValueError('Choose 1–4 distinct relative paths')
    for name in files:
        patch_tasks.patch_path(name)
    python_files = [name for name in files if Path(name).suffix == '.py']
    source = Path(project['source'])
    has_tests = (source / 'tests').is_dir() and any((source / 'tests').glob('test_*.py'))
    print('Checks: 1 = Python syntax, 2 = existing Python tests, 3 = both')
    default = '3' if python_files and has_tests else '2' if has_tests else '1'
    choice = input('Checks [' + default + ']: ').strip() or default
    if choice not in {'1', '2', '3'} or (choice in {'1', '3'} and not python_files) or (choice in {'2', '3'} and not has_tests):
        raise ValueError('Choose available Python syntax or unittest checks for this project')
    checks = []
    if choice in {'1', '3'}:
        checks.append({'command': 'python.syntax', 'files': python_files})
    if choice in {'2', '3'}:
        checks.append({'command': 'python.tests'})
    return files, checks


async def approve(task: dict, *, rollback: bool = False) -> bool:
    review = patch_promotion.review(task['id'], rollback=rollback)
    print('\nReview for ' + json.dumps(review['source']))
    for change in review['changes']:
        action = 'Delete' if not change['after_exists'] else 'Create' if not change['before_exists'] else 'Update'
        print(action + ': ' + json.dumps(change['path']))
    display(review['diff'])
    verb = 'UNDO' if rollback else 'APPLY'
    confirmation = verb + ' ' + review['patch_sha256'][:12]
    entered = input('Type ' + confirmation + ' to confirm, or press Enter to keep the current files: ').strip()
    if entered != confirmation:
        print('Review saved. Task: ' + task['id'])
        return False
    token = patch_promotion.authorize(task['id'], review['patch_sha256'], 'rollback' if rollback else 'apply')
    result = await patch_promotion.promote(task['id'], token, rollback=rollback)
    print(('Original files restored. ' if rollback else 'Changes applied. ') + 'Task: ' + result['id'])
    return True


async def main() -> None:
    import sys
    if not sys.stdin.isatty():
        raise ValueError('The project workshop requires an interactive terminal')
    print('ROMS project workshop — choose files, describe a change, and review the checked draft.')
    print('This test build supports Python syntax and unittest checks. Selected files may total up to 4 KiB.')
    project = await select_project()
    files, checks = select_files(project)
    print('Describe a change. Use /find NAME for code locations, /files to change the selection, /repair TASK_ID for one failed check, or /exit to return.')
    while True:
        instruction = input('\nChange: ').strip()
        if instruction == '/exit':
            return
        if instruction == '/files':
            files, checks = select_files(project)
            continue
        if instruction.startswith('/find '):
            try:
                found = CodeIndex(Path(project['source'])).query(instruction[6:].strip())
                display(json.dumps(found, indent=2))
                print('Locations are advisory. Use /files to select editable files explicitly.')
            except (OSError, ValueError) as error:
                display(str(error))
            continue
        if not instruction:
            continue
        try:
            if instruction.startswith('/repair '):
                parent_id = instruction[8:].strip()
                _, _, parent_patch = patch_tasks.load_task(parent_id)
                if parent_patch['project_id'] != project['id']:
                    raise ValueError('Select the project belonging to this failed task before repairing it')
                print('ROMS is drafting one repair from the recorded failed check...', flush=True)
                draft = await project_repair.draft_repair(parent_id)
            else:
                print('ROMS is drafting the change...', flush=True)
                draft = await project_assistant.draft_change(project['id'], files, instruction, checks)
            task = draft['task']
            print('Draft saved. Running the selected checks. Task: ' + task['id'], flush=True)
            response = await asyncio.to_thread(task_worker_client.request, 'task.validate', {'task_id': task['id']})
            if not response['ok']:
                detail = response.get('task', {}).get('error', response.get('detail', response['error']))
                display('Checks did not pass: ' + detail)
                _, failed_task, _ = patch_tasks.load_task(task['id'])
                for evidence in failed_task.get('evidence', []):
                    display(compact_log(evidence.get('output', ''))['text'])
                print('Inspect this draft with goose --show-patch ' + task['id'])
                print('Request one repair with /repair ' + task['id'] + '. No repair is started automatically.')
                continue
            print('Selected checks passed. Review the actual changes below.')
            advisory = await review_task(task['id'], Collector())
            print('Advisory code review: ' + advisory['status'])
            for finding in advisory.get('findings', [])[:20]:
                display(json.dumps(finding, ensure_ascii=True))
            if advisory.get('reason'):
                display(advisory['reason'])
            print('Evidence receipt: ' + advisory['receipt']['id'])
            if await approve(response['task']):
                if input('Press Enter for another change, or type UNDO to review a rollback: ').strip() == 'UNDO':
                    await approve(response['task'], rollback=True)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, httpx.HTTPError) as error:
            display('Change request stopped: ' + str(error))


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (EOFError, KeyboardInterrupt):
        print('\nProject workshop closed.')
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit('Project workshop: ' + json.dumps(str(error))) from error
