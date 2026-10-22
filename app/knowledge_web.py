"""Loopback-only Add knowledge interface using the existing HTTP stack."""
import argparse
from contextlib import asynccontextmanager
from pathlib import Path
import secrets

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route
from app.document_parse import MAX_FILE_BYTES
from app.knowledge_catalog import catalog
from app.knowledge_intake import Intake


def create_app(intake, token, port=8845, start_worker=True):
    allowed_hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            intake.start()
        yield
        intake.stop.set()

    async def home(request):
        return HTMLResponse(Path(__file__).with_name('knowledge_ui.html').read_text(encoding='utf-8'))

    async def upload(request):
        body = bytearray()
        async for block in request.stream():
            body.extend(block)
            if len(body) > MAX_FILE_BYTES:
                return JSONResponse({'error': 'Maximum file size is 32 MiB'}, status_code=413)
        try:
            job = await run_in_threadpool(intake.submit, request.query_params.get('name', ''), bytes(body))
            return JSONResponse({'id': job, 'state': 'queued'}, status_code=202)
        except ValueError as error:
            return JSONResponse({'error': str(error)}, status_code=400)

    async def jobs(request):
        return JSONResponse(await run_in_threadpool(intake.status, request.query_params.get('offset', 0)))

    async def navigation(request):
        return JSONResponse(await run_in_threadpool(catalog, intake.db_path, request.query_params.get('offset', 0)))

    async def retry(request):
        retried = await run_in_threadpool(intake.retry, request.path_params['job'])
        return JSONResponse({'queued': retried}, status_code=202 if retried else 409)

    async def source(request):
        from app.db import get_connection
        def read():
            conn = get_connection(intake.db_path, reuse=False)
            try:
                row = conn.execute('SELECT doc_id,content FROM fts_chunks WHERE chunk_id=?',
                                   (int(request.path_params['chunk']),)).fetchone()
                return {'doc_id': row[0], 'content': row[1]} if row else None
            finally:
                conn.close()
        result = await run_in_threadpool(read)
        return JSONResponse(result or {'error': 'Source no longer exists'}, status_code=200 if result else 404)

    async def search(request):
        from app.zgsearch import zg_search
        query = request.query_params.get('q', '').strip()
        if not query or len(query) > 2000:
            return JSONResponse({'error': 'Enter a query of 1–2,000 characters'}, status_code=400)
        result = await run_in_threadpool(zg_search, query, limit=10, db_path=intake.db_path)
        return JSONResponse({'results': result})

    async def skills(request):
        from app.knowledge_skills import list_drafts
        return JSONResponse(await run_in_threadpool(list_drafts, intake.db_path,
                            request.query_params.get('q', ''), request.query_params.get('offset', 0)))

    async def brief(request):
        import json
        from app.knowledge_brief import prepare
        body = bytearray()
        async for block in request.stream():
            body.extend(block)
            if len(body) > 32768:
                return JSONResponse({'error': 'Brief request exceeds 32 KiB'}, status_code=413)
        try:
            data = json.loads(body)
        except (ValueError, UnicodeError):
            raise ValueError('Brief request must be valid JSON')
        if type(data) is not dict or set(data) != {'task', 'constraints', 'chunk_ids'}:
            raise ValueError('Supply task, constraints and chunk_ids')
        return JSONResponse(await run_in_threadpool(prepare, data['task'], data['chunk_ids'],
                                                   data['constraints'], intake.db_path))

    async def skill_detail(request):
        from app.knowledge_skills import get_draft, render_markdown
        draft = await run_in_threadpool(get_draft, request.path_params['skill_id'], intake.db_path)
        if not draft:
            return JSONResponse({'error': 'Skill sources no longer exist'}, status_code=404)
        if request.query_params.get('export') == '1':
            if request.query_params.get('revision') != draft['revision']:
                return JSONResponse({'error': 'Sources changed; review the current draft first'}, status_code=409)
            return PlainTextResponse(render_markdown(draft), headers={
                'Content-Disposition': 'attachment; filename="SKILL.md"'})
        return JSONResponse(draft)

    async def skill_refresh(request):
        from app.knowledge_skills import rebuild
        return JSONResponse(await run_in_threadpool(rebuild, intake.db_path))

    async def skill_feedback(request):
        import json
        from app.knowledge_skills import record_feedback
        body = bytearray()
        async for block in request.stream():
            body.extend(block)
            if len(body) > 8192:
                return JSONResponse({'error': 'Feedback exceeds 8 KiB'}, status_code=413)
        try:
            data = json.loads(body)
        except (ValueError, UnicodeError):
            raise ValueError('Feedback must be valid JSON')
        if type(data) is not dict or set(data) != {'revision', 'outcome', 'note', 'event_id'}:
            raise ValueError('Feedback requires revision, outcome, note and event_id')
        return JSONResponse(await run_in_threadpool(record_feedback, request.path_params['skill_id'],
                            data['revision'], data['outcome'], data['note'], data['event_id'], intake.db_path))

    app = Starlette(routes=[Route('/', home), Route('/api/upload', upload, methods=['POST']),
                            Route('/api/jobs', jobs), Route('/api/brief', brief, methods=['POST']),
                            Route('/api/skills', skills), Route('/api/skills/refresh', skill_refresh, methods=['POST']),
                            Route('/api/skills/{skill_id}', skill_detail),
                            Route('/api/skills/{skill_id}/feedback', skill_feedback, methods=['POST']), Route('/api/catalog', navigation),
                            Route('/api/retry/{job}', retry, methods=['POST']), Route('/api/search', search), Route('/api/source/{chunk:int}', source)], lifespan=lifespan)

    async def protect(request: Request, call_next):
        host = request.headers.get('host', '')
        origin = request.headers.get('origin')
        if host not in allowed_hosts or (origin and origin != 'http://' + host):
            return JSONResponse({'error': 'Local same-origin requests only'}, status_code=403)
        if request.url.path.startswith('/api/') and not secrets.compare_digest(request.headers.get('x-roms-token', ''), token):
            return JSONResponse({'error': 'Open the private link printed by ROMS'}, status_code=401)
        try:
            response = await call_next(request)
        except ValueError as error:
            response = JSONResponse({'error': str(error)}, status_code=400)
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                                 'Referrer-Policy': 'no-referrer',
                                 'Content-Security-Policy': "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
        return response
    from starlette.middleware.base import BaseHTTPMiddleware
    app.add_middleware(BaseHTTPMiddleware, dispatch=protect)
    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description='Open ROMS local knowledge intake, catalog and search')
    parser.add_argument('--port', type=int, default=8845)
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error('port must be between 1024 and 65535')
    token = secrets.token_urlsafe(32)
    app = create_app(Intake(), token, args.port)
    print(f'Open http://127.0.0.1:{args.port}/#token={token}', flush=True)
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=args.port)
