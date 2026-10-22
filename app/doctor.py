"""Read-only, bounded explanation of broker health; no operational probes."""
from __future__ import annotations

import json
import socket
import sys
import time
from typing import Any

from app.json_protocol import unique_object

SOCKET_PATH = '/run/omarchy-broker/broker.sock'
MAX_FRAME = 65536
TIMEOUT = 10.0
UNKNOWN = 'not reported or unrecognized'
PLATFORM = sys.platform


class UnsupportedTransportError(RuntimeError):
    """The broker's Linux socket cannot be queried from this environment."""


def _invalid_constant(value: str) -> None:
    raise ValueError('Non-finite number')


def read_status() -> dict[str, Any]:
    """Send only STATUS, bounded by a total deadline and one response frame."""
    family = getattr(socket, 'AF_UNIX', None)
    if PLATFORM != 'linux' or family is None:
        raise UnsupportedTransportError('Linux broker transport is unavailable')
    deadline = time.monotonic() + TIMEOUT
    with socket.socket(family) as client:
        client.settimeout(TIMEOUT)
        client.connect(SOCKET_PATH)
        client.settimeout(max(0.001, deadline - time.monotonic()))
        client.sendall(b'STATUS\n')
        data = bytearray()
        while b'\n' not in data:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Status deadline exceeded')
            client.settimeout(remaining)
            chunk = client.recv(min(4096, MAX_FRAME + 1 - len(data)))
            if not chunk:
                raise ValueError('Incomplete status')
            data.extend(chunk)
            if len(data) > MAX_FRAME:
                raise ValueError('Status too large')
    if data.count(b'\n') != 1 or not data.endswith(b'\n'):
        raise ValueError('Expected one status frame')
    status = json.loads(data.decode('utf-8'), object_pairs_hook=unique_object,
                        parse_constant=_invalid_constant)
    if (type(status) is not dict or status.get('ok') is not True
            or type(status.get('features')) is not dict):
        raise ValueError('Invalid status response')
    return status


def _label(value: object, labels: dict[str, str]) -> str:
    return labels.get(value, UNKNOWN) if isinstance(value, str) else UNKNOWN


def _feature(status: dict[str, Any], name: str) -> object:
    feature = status['features'].get(name)
    return feature.get('state') if type(feature) is dict else None


def explain(status: dict[str, Any]) -> tuple[str, int]:
    """Render fixed labels only; never echo arbitrary reasons, paths or errors."""
    model = status.get('rwkv7')
    memory = status.get('roms')
    chat = _feature(status, 'chat')
    worker = _feature(status, 'validation_worker')
    workshop = _feature(status, 'project_workshop')
    native = _feature(status, 'native_project_chat')
    core_ready = model == 'ready' and memory == 'ready' and chat == 'ready'
    workshop_available = core_ready and worker == 'reachable' and workshop == 'available'
    attention = not workshop_available or native == 'cleanup_required'
    lines = [
        'ROMS doctor - read-only readiness',
        'Result: attention needed' if attention else 'Result: chat ready; workshop prerequisites available',
        'Broker: reachable (status request completed)',
        'Local model: ' + _label(model, {'ready': 'ready (reported by live model health)',
                                        'not_connected': 'not connected'}),
        'Knowledge service: ' + _label(memory, {'ready': 'ready (service health only)',
                                               'degraded': 'degraded', 'unavailable': 'unavailable'}),
        'Chat: ' + ('ready' if core_ready else 'not ready or not fully reported'),
        'Validation worker: ' + _label(worker, {'reachable': 'reachable; sandbox enforcement was not tested',
                                               'unavailable': 'unavailable'}),
        'Project workshop: ' + ('prerequisites available; each draft still needs checks and review'
                                if workshop_available else 'unavailable or prerequisites not fully reported'),
        'Native project chat: ' + _label(native, {
            'idle': 'configured and idle; no loaded model session verified by this check',
            'running': 'request active; successful completion is not yet verified',
            'unconfigured': 'not configured',
            'cleanup_required': 'cleanup required; new native requests are blocked'}),
    ]
    for name, title in (('knowledge_library', 'Library indexing'), ('project_memory', 'Project memory')):
        lines.append(title + ': ' + _label(_feature(status, name), {'not_probed': 'not tested by status'}))
    for name, title in (('desktop_control', 'Desktop control'), ('recurrent_state', 'Broker conversation restore'),
                        ('web_evidence', 'Web evidence'), ('guest_delegation', 'Guest models'),
                        ('training', 'Training')):
        lines.append(title + ': ' + _label(_feature(status, name), {'unavailable': 'unavailable in this broker'}))
    lines.append('Arbitrary command execution: ' + _label(_feature(status, 'arbitrary_execution'),
                                                         {'disabled': 'disabled'}))
    lines.append('\nNext steps:')
    if not core_ready:
        lines.append('- After a cold start, allow up to 90 seconds and run goose --doctor again.')
        lines.append('- If still unavailable, inspect: systemctl status goose-model goose-roms omarchy-broker --no-pager')
    if worker != 'reachable':
        lines.append('- Inspect the validation service: systemctl --user status omarchy-task-worker --no-pager')
    if core_ready and worker == 'reachable' and workshop != 'available':
        lines.append('- Workshop access is not confirmed. Review the local gateway configuration; do not share credential values.')
    if native == 'cleanup_required':
        lines.append('- Stop submitting native requests and review the broker diagnostics for retained work before recovery.')
    if core_ready:
        lines.append('- Start chat with goose; manage imported text with goose --library.')
    if workshop_available:
        lines.append('- Use goose --project-workshop to prepare a small change for checks and review.')
    lines.append('\nThis is a readiness snapshot, not a release certification. No model generation, indexing, validation, repair or service restart was requested.')
    return '\n'.join(lines), int(attention)


def run() -> int:
    try:
        report, code = explain(read_status())
    except UnsupportedTransportError:
        report, code = ('ROMS doctor: this environment cannot access the Linux broker socket.\n'
                        'Run goose --doctor inside the configured Linux/Omarchy environment. On Windows, open Omarchy in WSL first. No connection or service change was attempted.'), 1
    except PermissionError:
        report, code = ('ROMS doctor: broker access denied.\n'
                        'Run this as the configured Omarchy user. Inspect the broker service ownership; do not broaden socket permissions.'), 1
    except (TimeoutError, socket.timeout):
        report, code = ('ROMS doctor: broker status timed out.\n'
                        'Allow cold startup to finish, then retry. If it persists, inspect systemctl status omarchy-broker --no-pager.'), 1
    except (ConnectionError, FileNotFoundError):
        report, code = ('ROMS doctor: broker is unavailable.\n'
                        'Use the Omarchy environment and inspect systemctl status omarchy-broker --no-pager. No service was started.'), 1
    except OSError:
        report, code = ('ROMS doctor: broker status could not be read.\n'
                        'Inspect systemctl status omarchy-broker --no-pager. No repair was attempted.'), 1
    except (ValueError, RecursionError):
        report, code = ('ROMS doctor: broker returned an invalid or incomplete status.\n'
                        'Check that the installed broker and client versions match. No response details were displayed.'), 1
    print(report)
    return code
