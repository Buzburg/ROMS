"""Authenticated local schema-constrained drafting through the pinned native runtime."""
import json
import os
from urllib.parse import urlsplit

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import ROMS_UPSTREAM_LLM_URL
from app.json_protocol import unique_object
from app.project_contract import draft_prompt, response_schema, validate_payload
from app.request_lifecycle import ClientDisconnected, while_connected


async def native_json(client: httpx.AsyncClient, url: str, body: dict, headers: dict) -> dict:
    async with client.stream('POST', url, json=body, headers=headers) as response:
        response.raise_for_status()
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > 65536:
                raise ValueError('Native response exceeds the draft limit')
    value = json.loads(data.decode('utf-8'), object_pairs_hook=unique_object)
    if type(value) is not dict:
        raise ValueError('Invalid native response')
    return value


async def draft_completion(request: Request) -> JSONResponse:
    if not os.getenv('ROMS_GATEWAY_API_KEY'):
        return JSONResponse({'error': 'Configure gateway authentication before project drafting'}, status_code=503)
    try:
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 32768:
                return JSONResponse({'error': 'Draft request too large'}, status_code=413)
        payload = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object)
        validate_payload(payload)
    except (ValueError, UnicodeError, RecursionError, TypeError) as error:
        return JSONResponse({'error': str(error)[:256]}, status_code=400)
    try:
        return await while_connected(request, lambda: generate_draft(payload))
    except ClientDisconnected:
        return JSONResponse({'error': 'Client disconnected; draft cancelled'}, status_code=499)


async def generate_draft(payload: dict) -> JSONResponse:
    try:
        upstream = urlsplit(ROMS_UPSTREAM_LLM_URL)
        if (upstream.scheme != 'http' or upstream.hostname not in {'127.0.0.1', '::1', 'localhost'}
                or upstream.username or upstream.password or upstream.path != '/v1' or upstream.query or upstream.fragment):
            raise ValueError('Project drafting requires the configured local native runtime')
        origin = f'{upstream.scheme}://{upstream.netloc}'
        headers = {'Authorization': 'Bearer ' + os.getenv('ROMS_UPSTREAM_API_KEY', '')}
        messages = [{'role': 'system', 'content': 'You are ROMS, a local code drafting assistant. Return only the requested draft JSON.'},
                    {'role': 'user', 'content': draft_prompt(payload)}]
        async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
            template = await native_json(client, origin + '/apply-template', {'messages': messages}, headers)
            prompt = template['prompt']
            if not isinstance(prompt, str) or len(prompt.encode('utf-8')) > 32768:
                raise ValueError('Invalid native prompt template result')
            tokens = await native_json(client, origin + '/tokenize', {'content': prompt, 'add_special': True}, headers)
            if type(tokens.get('tokens')) is not list or len(tokens['tokens']) > 3072:
                return JSONResponse({'error': 'Selected input exceeds the model context budget; select fewer or smaller files'}, status_code=400)
            generated = await native_json(client, origin + '/completion', {
                'prompt': prompt, 'json_schema': response_schema(list(payload['files'])),
                'n_predict': 768, 'temperature': 0.0, 'stream': False, 'cache_prompt': False}, headers)
        content = generated['content']
        if not isinstance(content, str) or len(content.encode('utf-8')) > 16384:
            raise ValueError('Native draft output exceeds its limit')
        finished = not generated.get('truncated') and generated.get('stop_type') in {'eos', 'word'}
        return JSONResponse({'model': generated.get('model'),
            'choices': [{'finish_reason': 'stop' if finished else 'length', 'message': {'role': 'assistant', 'content': content}}],
            'usage': {'prompt_tokens': generated.get('tokens_evaluated'), 'completion_tokens': generated.get('tokens_predicted')}})
    except (httpx.HTTPError, ValueError, KeyError, TypeError, RecursionError):
        return JSONResponse({'error': 'Local structured drafting failed; no project files were changed'}, status_code=502)
