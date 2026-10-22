"""Local OS controls: inspect services and review a real installed app launch."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

import httpx

from app import os_operator
from app.json_protocol import unique_object


def display(value: object) -> None:
    print(json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False))


def show_error(error: os_operator.OSOperatorError) -> None:
    unit = getattr(error, 'unit', None)
    display({'error': error.code, 'message': str(error), 'unit': unit})
    if unit:
        print('Inspect the displayed unit before retrying: systemctl --user status -- ' + json.dumps(unit))


async def inspect_services() -> list[dict[str, Any]]:
    return [await os_operator.service_status(name) for name in
            ('goose-model', 'goose-roms', 'omarchy-broker', 'omarchy-task-worker')]


async def request_plan(instruction: str, apps: list[dict[str, str]]) -> dict[str, str | None]:
    if not instruction.strip() or len(instruction.encode('utf-8')) > 1024:
        raise ValueError('Describe one action using at most 1024 bytes')
    key = os.getenv('ROMS_GATEWAY_API_KEY')
    if not key:
        raise ValueError('Open the system workshop through the installed ROMS launcher')
    port = int(os.getenv('ROMS_GATEWAY_PORT', '8844'))
    if not 1 <= port <= 65535:
        raise ValueError('Invalid local gateway port')
    body = {'instruction': instruction, 'apps': [{'id': app['id'], 'name': app['name']} for app in apps]}
    async with asyncio.timeout(120), httpx.AsyncClient(timeout=120, trust_env=False) as client:
        async with client.stream('POST', f'http://127.0.0.1:{port}/v1/os/plan', json=body,
                                 headers={'Authorization': 'Bearer ' + key}) as response:
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 16384:
                    raise ValueError('ROMS returned an oversized plan; no action was taken')
    value = json.loads(data, object_pairs_hook=unique_object)
    plan = value.get('plan') if type(value) is dict else None
    if type(plan) is not dict or set(plan) != {'action', 'app_id'}:
        raise ValueError('ROMS returned an invalid plan; no action was taken')
    action, app_id = plan['action'], plan['app_id']
    if action in ('inspect_services', 'none') and app_id is None:
        return plan
    if action == 'launch_app' and type(app_id) is str and app_id in {app['id'] for app in apps}:
        return plan
    raise ValueError('ROMS selected an unavailable action; no action was taken')


async def review_plan(plan: dict[str, str | None], apps: list[dict[str, str]]) -> None:
    if plan['action'] == 'inspect_services':
        display(await inspect_services())
    elif plan['action'] == 'launch_app':
        selected = next((app for app in apps if app['id'] == plan['app_id']), None)
        if selected is None:
            raise ValueError('The selected app is no longer in this catalog')
        print('ROMS proposes opening: ' + json.dumps(selected['name'], ensure_ascii=True))
        confirmation = 'OPEN ' + selected['id']
        if input('Type ' + confirmation + ' to open it, or Enter to cancel: ').strip() == confirmation:
            display(await os_operator.launch(selected['id'], selected['file_sha256']))
        else:
            print('No app was launched.')
    elif plan['action'] == 'none' and plan['app_id'] is None:
        print('This request has no supported system action yet. Use /project for reviewed code repairs.')
    else:
        raise ValueError('Unsupported system action')


async def workshop() -> None:
    if not sys.stdin.isatty():
        raise ValueError('System controls require an interactive terminal; --inspect is read-only')
    print('ROMS system workshop: service health and installed application launch.')
    print('In-app clicks, typing, privileged OS repair and Windows application control are not available yet.')
    while True:
        print('\n1. Inspect ROMS services\n2. List and open an installed app\n3. Ask ROMS for a supported action\n0. Return')
        choice = input('Choose: ').strip()
        if choice in {'', '0', '/exit'}:
            return
        try:
            if choice == '1':
                display(await inspect_services())
                continue
            if choice not in {'2', '3'}:
                raise ValueError('Choose one of the listed actions')
            catalog = os_operator.inventory()
            apps = catalog['apps']
            if choice == '3':
                instruction = input('What should ROMS do? ').strip()
                plan = await request_plan(instruction, apps)
                await review_plan(plan, apps)
                continue
            display(catalog)
            for index, app in enumerate(apps, 1):
                print(str(index) + '. ' + json.dumps(app['name'], ensure_ascii=True))
            selected = input('App number to open (Enter returns): ').strip()
            if not selected:
                continue
            if not selected.isdecimal() or not 1 <= int(selected) <= len(apps):
                raise ValueError('Choose an app from this list')
            app = apps[int(selected) - 1]
            display(await os_operator.launch(app['id'], app['file_sha256']))
        except os_operator.OSOperatorError as error:
            show_error(error)
        except (httpx.HTTPError, TimeoutError):
            print('The local request failed or timed out. No automatic retry was made.')
        except ValueError as error:
            display({'error': str(error)[:256]})


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--inspect', action='store_true', help='Read-only service status as JSON')
    mode.add_argument('--list-apps', action='store_true', help='Read-only eligible application catalog')
    args = parser.parse_args()
    if args.inspect:
        display(await inspect_services())
    elif args.list_apps:
        display(os_operator.inventory())
    else:
        await workshop()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (EOFError, KeyboardInterrupt):
        print('\nSystem workshop closed.')
    except os_operator.OSOperatorError as error:
        show_error(error)
        raise SystemExit(1)
    except ValueError as error:
        display({'error': str(error)[:256]})
        raise SystemExit(1)
