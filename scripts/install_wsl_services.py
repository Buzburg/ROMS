"""Install unprivileged local services in the custom Omarchy WSL distribution."""
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit('Run as root inside the Omarchy distribution')
    root = Path(__file__).resolve().parents[1]
    workspace = root.parent
    home = Path('/home/rryan')
    config = home / '.config/goose'
    config.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = home / '.local/share/omarchy-harness/roms'
    data.mkdir(parents=True, exist_ok=True)
    workers = data.parent / 'workspaces'
    workers.mkdir(parents=True, exist_ok=True, mode=0o700)
    source_db = root / 'data/roms.db'
    if source_db.is_file() and not (data / 'roms.db').exists():
        with sqlite3.connect(f'file:{source_db}?mode=ro', uri=True) as source:
            with sqlite3.connect(data / 'roms.db') as destination:
                source.backup(destination)
    cache = home / '.cache/huggingface/hub'
    cache.mkdir(parents=True, exist_ok=True)
    subprocess.run(['tar', '-xf', str(workspace / 'deployment/downloads/embedding-cache.tar'), '-C', str(cache)], check=True)
    app = Path('/opt/omarchy-harness')
    if not app.exists():
        app.symlink_to(root, target_is_directory=True)
    elif app.resolve() != root:
        raise RuntimeError('Existing /opt/omarchy-harness points elsewhere')
    envfile = config / 'runtime.env'
    if not envfile.exists():
        upstream = secrets.token_hex(32)
        gateway = secrets.token_hex(32)
        envfile.write_text(f'ROMS_GATEWAY_API_KEY={gateway}\nROMS_UPSTREAM_API_KEY={upstream}\n'
                          f'LLAMA_API_KEY={upstream}\nROMS_UPSTREAM_LLM_URL=http://127.0.0.1:18080/v1\n'
                          f'ROMS_DATA_DIR={data}\nROMS_MODEL_ALIAS=goose-2.9b\nTZ=America/Chicago\n'
                          'HF_HUB_OFFLINE=1\nROMS_ENABLE_EXPERIMENTAL_EXECUTION=0\n')
    envfile.chmod(0o600)
    settings = dict(line.split('=', 1) for line in envfile.read_text().splitlines() if '=' in line)
    settings['ROMS_EMBEDDING_MODEL'] = 'embeddinggemma-q8'
    settings['ROMS_PYTHON_PREFIX'] = '/opt/roms-env'
    settings['ROMS_WORKSPACES_DIR'] = str(workers)
    envfile.write_text(''.join(f'{key}={value}\n' for key, value in settings.items()))
    launcher = Path('/usr/local/bin/goose')
    launcher.write_text('#!/bin/bash\nset -euo pipefail\nset -a\n'
                        'source "$HOME/.config/goose/runtime.env"\nset +a\n'
                        'exec "$ROMS_PYTHON_PREFIX/bin/python" /opt/omarchy-harness/scripts/goose.py "$@"\n')
    launcher.chmod(0o755)
    model = workspace / 'rwkv7-g1g-2.9b-Q4_K_M.gguf'
    common = ('[Service]\nType=simple\nUser=rryan\nGroup=rryan\n'
              f'EnvironmentFile={envfile}\nRestart=on-failure\nRestartSec=5\n'
              'NoNewPrivileges=true\nUMask=0077\nTimeoutStopSec=30\n')
    units = {
        'goose-model': '[Unit]\nDescription=ROMS local inference\nAfter=local-fs.target\n' + common +
            'Environment=LD_LIBRARY_PATH=/opt/goose-runtime/bin\n'
            f'ExecStart=/opt/goose-runtime/bin/llama-server -m "{model}" --host 127.0.0.1 --port 18080 '
            '-c 4096 -np 1 -b 64 -ub 64 -t 4 -ngl 0 --no-warmup --jinja --reasoning auto --reasoning-format deepseek '
            '--chat-template-file /opt/omarchy-harness/config/rwkv-user-assistant.jinja --alias goose-2.9b\n',
        'goose-roms': '[Unit]\nDescription=ROMS local memory gateway\nAfter=goose-model.service\n' + common +
            'ExecStart=/usr/bin/python /opt/omarchy-harness/scripts/run_linux_env.py python -m app.gateway\n',
        'omarchy-broker': '[Unit]\nDescription=Omarchy Mojo local broker\nAfter=goose-roms.service\n' + common +
            'RuntimeDirectory=omarchy-broker\nRuntimeDirectoryMode=0700\n'
            'Environment=OMARCHY_BROKER_SOCKET=/run/omarchy-broker/broker.sock\n'
            'ExecStart=/usr/bin/python /opt/omarchy-harness/scripts/run_linux_env.py omarchy-broker\n',
    }
    for name, content in units.items():
        Path(f'/etc/systemd/system/{name}.service').write_text(content + '\n[Install]\nWantedBy=multi-user.target\n')
    subprocess.run(['chown', '-R', 'rryan:rryan', str(home)], check=True)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', *[name + '.service' for name in units]], check=True)
    from install_task_worker import install
    install()
    print('Installed services; use goose --status to check actual readiness.')


if __name__ == '__main__':
    main()
