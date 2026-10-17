"""Verify the WSL test-build profile; unavailable required checks fail closed."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def wait_for_services(command: list[str], root: Path, env: dict[str, str], timeout: float = 90) -> subprocess.CompletedProcess:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Local model and ROMS did not become ready within the startup deadline')
        try:
            result = subprocess.run(command, cwd=root, env=env, text=True, capture_output=True,
                                    timeout=min(10, remaining))
            if result.returncode == 0:
                status = json.loads(result.stdout)
                if status.get('rwkv7') == 'ready' and status.get('roms') == 'ready':
                    return result
        except subprocess.TimeoutExpired:
            pass
        time.sleep(min(1, max(0, deadline - time.monotonic())))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='Check code only, without running services')
    parser.add_argument('--containers', action='store_true', help='Require live rootless worker lifecycle checks')
    parser.add_argument('--sandbox', action='store_true', help='Require native and combined confinement checks')
    parser.add_argument('--staging', action='store_true', help='Require real fixture patch staging and validation')
    parser.add_argument('--drafts', action='store_true', help='Require a real model draft through validation, apply and rollback')
    parser.add_argument('--os-operator', action='store_true', help='Require actual Goose plans and a test-owned graphical app launch')
    parser.add_argument('--native-adapter', action='store_true', help='Require actual C ABI and compiled Mojo model checks')
    parser.add_argument('--native-chat', action='store_true', help='Require actual Mojo worker conversations and process cleanup')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    prefix = Path(os.getenv('ROMS_PYTHON_PREFIX', str(root / '.pixi/envs/default')))
    binary = Path(os.getenv('OMARCHY_BROKER_BINARY', str(prefix / 'bin/omarchy-broker')))
    suites = ['release_safety', 'memory', 'context', 'retrieval_quality', 'search_upgrades', 'search_native', 'ingestion_quality', 'messy_ingestion',
              'tools_quality', 'throttle', 'broker_actions', 'broker_protocol', 'broker_requests', 'broker_scheduler', 'goose_response', 'request_lifecycle', 'gateway_disconnect', 'gateway_privacy', 'gateway_prompt', 'doctor', 'workbench_package', 'os_operator', 'os_model', 'os_workshop', 'project_repair', 'voice_audio', 'voice_chat', 'voice_stt', 'voice_tts', 'voice_workshop', 'document_identity', 'source_library', 'build_readiness', 'validation_policy', 'model_inputs', 'runtime_patch']
    checks = [
        ('ROMS offline regressions', [sys.executable, '-m', 'pytest',
            *[f'tests/test_{name}.py' for name in suites], '-q', '--tb=short']),
        ('Compiled native broker', [sys.executable, '-m', 'pytest', 'tests/test_omarchy_broker.py',
                                    'tests/test_broker_concurrency.py', 'tests/test_broker_memory.py',
                                    'tests/test_broker_chat.py', '-q', '--tb=short']),
    ]
    if not args.offline:
        checks.append(('Live model and ROMS', ['/usr/local/bin/goose', '--status']))
    if args.native_adapter:
        checks.append(('Native model ABI', [sys.executable, '-m', 'pytest', 'tests/test_native_adapter.py',
                                          'tests/test_native_answer.py', 'tests/test_mojo_model_binding.py', '-q', '--tb=short']))
    if args.native_chat:
        checks.append(('Native broker conversations', [sys.executable, '-m', 'pytest',
                       'tests/test_native_chat.py', '-q', '--tb=short']))
    if args.containers:
        checks.append(('Rootless worker lifecycle', [sys.executable, '-m', 'pytest',
                       'tests/test_container_lifecycle.py', '-q', '--tb=short']))
    if args.sandbox:
        checks.append(('Native and combined sandbox', [sys.executable, '-m', 'pytest',
                       'tests/test_native_sandbox.py', 'tests/test_combined_sandbox.py', '-q', '--tb=short']))
    if args.staging:
        checks.append(('Staged patch validation', [sys.executable, '-m', 'pytest',
                       'tests/test_patch_staging.py', 'tests/test_patch_promotion.py', '-q', '--tb=short']))
        checks.append(('Project validation service', [sys.executable, '-m', 'pytest', 'tests/test_task_worker.py',
                       'tests/test_worker_recovery.py', '-q', '--tb=short']))
        if not args.offline:
            checks.append(('Installed project worker boundary', [sys.executable, 'scripts/verify_task_worker_service.py']))
    if args.drafts:
        checks.append(('Model-assisted project workflow', [sys.executable, '-m', 'pytest',
                       'tests/test_project_assistant.py', 'tests/test_project_repair.py', 'tests/test_project_model.py', 'tests/test_rwkv_prompt.py',
                       'tests/test_gateway_cancellation_live.py', '-q', '--tb=short']))
        checks.append(('Memory-grounded live chat', [sys.executable, '-m', 'pytest',
                       'tests/test_broker_chat_live.py', '-q', '--tb=short']))
    if args.os_operator:
        checks.append(('Installed OS operator', [sys.executable, '-m', 'pytest',
                       'tests/test_os_operator_live.py', '-q', '--tb=short']))
    failed = 0
    env = dict(os.environ, OMARCHY_BROKER_BINARY=str(binary))
    print('WSL test build. Tool execution, training and full desktop are not certified.')
    for name, command in checks:
        try:
            if name == 'Compiled native broker' and not binary.is_file():
                raise FileNotFoundError(f'Required current-build artifact missing: {binary}')
            if name == 'Native model ABI':
                for variable in ('OMARCHY_NATIVE_ADAPTER', 'OMARCHY_STATE_MODEL'):
                    if not env.get(variable) or not Path(env[variable]).is_file():
                        raise ValueError(f'{variable} must identify the actual artifact; skipped tests cannot certify the ABI')
            if name == 'Native broker conversations':
                for variable in ('OMARCHY_NATIVE_CHAT_BINARY', 'OMARCHY_NATIVE_MODEL'):
                    if not env.get(variable) or not Path(env[variable]).is_file():
                        raise ValueError(f'{variable} must identify an actual artifact; skipped tests cannot certify native chat')
            if name == 'Rootless worker lifecycle' and not env.get('ROMS_LIVE_CONTAINER_IMAGE'):
                raise ValueError('ROMS_LIVE_CONTAINER_IMAGE must identify a reviewed local image; skipped tests cannot certify execution')
            if name in {'Model-assisted project workflow', 'Memory-grounded live chat'} and not env.get('ROMS_LIVE_DRAFT'):
                raise ValueError('ROMS_LIVE_DRAFT must explicitly enable the live model check; a skipped test cannot certify drafting')
            if name == 'Installed OS operator' and env.get('ROMS_LIVE_OS_OPERATOR') != '1':
                raise ValueError('ROMS_LIVE_OS_OPERATOR=1 must explicitly enable the real application launch check')
            if name in {'Native and combined sandbox', 'Staged patch validation', 'Project validation service', 'Model-assisted project workflow'}:
                if not env.get('OMARCHY_NATIVE_WORKER_IMAGE'):
                    raise ValueError('OMARCHY_NATIVE_WORKER_IMAGE must identify the built native sandbox image')
                sandbox = Path(env.get('OMARCHY_SANDBOX_BINARY', str(prefix / 'bin/staging-sandbox')))
                if not sandbox.is_file():
                    raise FileNotFoundError(f'Required native enforcement artifact missing: {sandbox}')
                env['OMARCHY_SANDBOX_BINARY'] = str(sandbox)
            result = (wait_for_services(command, root, env) if name == 'Live model and ROMS' else
                      subprocess.run(command, cwd=root, env=env, text=True, capture_output=True, timeout=180))
            passed = result.returncode == 0
            if name == 'Live model and ROMS' and passed:
                status = json.loads(result.stdout)
                passed = status.get('rwkv7') == 'ready' and status.get('roms') == 'ready'
            print(f'{"PASS" if passed else "FAIL"}: {name}')
            print((result.stdout + result.stderr)[-6000:])
            failed += not passed
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            print(f'INCOMPLETE: {name}: {error}')
            failed += 1
    print(f'{len(checks) - failed}/{len(checks)} required checks passed')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
