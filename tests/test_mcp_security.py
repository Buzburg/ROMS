"""Real MCP dispatch and side-effect regressions for the local server boundary."""
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import MiddlewareContext

from app.mcp_policy import MCPPolicy, tool_annotations, plugin_allowed


def context(name):
    return MiddlewareContext(message=SimpleNamespace(name=name))


def test_default_policy_denies_mutation_before_function_runs():
    server = FastMCP('policy-test', middleware=[MCPPolicy(profile='read_only')])
    calls = []

    @server.tool(annotations=tool_annotations('memory_retain'))
    def memory_retain():
        calls.append('write')
        return 'unexpected'

    @server.tool(annotations=tool_annotations('memory_get'))
    def memory_get():
        return 'read result'

    async def check():
        async with Client(server) as client:
            listing = {t.name: t for t in await client.list_tools()}
            assert listing['memory_get'].annotations.model_dump(by_alias=True)['readOnlyHint']
            assert not listing['memory_retain'].annotations.model_dump(by_alias=True)['readOnlyHint']
            with pytest.raises(ToolError, match='read_only'):
                await client.call_tool('memory_retain')
            assert (await client.call_tool('memory_get')).content[0].text == 'read result'
    asyncio.run(check())
    assert calls == []


def test_operator_profile_and_destructive_opt_in_are_separate():
    async def check():
        calls = []
        async def next_call(ctx):
            calls.append(ctx.message.name)
            return 'ok'
        policy = MCPPolicy(profile='local', allow_destructive=False)
        assert await policy.on_call_tool(context('memory_retain'), next_call) == 'ok'
        with pytest.raises(ToolError, match='Destructive'):
            await policy.on_call_tool(context('memory_forget'), next_call)
        enabled = MCPPolicy(profile='local', allow_destructive=True)
        assert await enabled.on_call_tool(context('memory_forget'), next_call) == 'ok'
        assert calls == ['memory_retain', 'memory_forget']
    asyncio.run(check())


def test_limits_enforce_concurrency_recovery_and_sliding_window():
    async def check():
        now = [0.0]
        policy = MCPPolicy(profile='local', max_concurrent=1, calls_per_minute=3, clock=lambda:now[0])
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow(ctx):
            entered.set()
            await release.wait()
            raise RuntimeError('fixture error')
        async def fast(ctx):return 'ok'
        running = asyncio.create_task(policy.on_call_tool(context('memory_get'), slow))
        await entered.wait()
        with pytest.raises(ToolError, match='concurrent'):
            await policy.on_call_tool(context('memory_get'), fast)
        release.set()
        with pytest.raises(RuntimeError):await running
        assert policy.inflight == 0
        assert await policy.on_call_tool(context('memory_get'), fast) == 'ok'
        with pytest.raises(ToolError, match='rate limit'):
            await policy.on_call_tool(context('memory_get'), fast)
        now[0] = 60
        assert await policy.on_call_tool(context('memory_get'), fast) == 'ok'
    asyncio.run(check())


@pytest.mark.parametrize('kwargs', [{'profile':'typo'},{'calls_per_minute':0},{'max_concurrent':0}])
def test_invalid_policy_fails_closed(kwargs):
    with pytest.raises(ValueError):MCPPolicy(**kwargs)


def test_plugin_import_and_hot_reload_need_explicit_operator_opt_ins(tmp_path, monkeypatch):
    from app import server, watcher
    root = tmp_path/'custom_tools';root.mkdir()
    marker = tmp_path/'executions.txt'
    source = f'from pathlib import Path\np=Path({str(marker)!r})\np.write_text(p.read_text()+"x" if p.exists() else "x")\n'
    (root/'approved.py').write_text(source)
    (root/'unapproved.py').write_text('raise RuntimeError("must never import")')
    monkeypatch.setattr(server, 'BASE_DIR', tmp_path)
    monkeypatch.setattr(watcher, 'BASE_DIR', tmp_path)
    for key in ['ROMS_MCP_PROFILE','ROMS_MCP_PLUGINS','ROMS_MCP_HOT_RELOAD']:
        monkeypatch.delenv(key,raising=False)
    server.load_custom_tools()
    watcher._reload_custom_tool(root/'approved.py')
    assert not marker.exists()
    monkeypatch.setenv('ROMS_MCP_PROFILE','local')
    monkeypatch.setenv('ROMS_MCP_PLUGINS','approved')
    server.load_custom_tools()
    assert marker.read_text() == 'x'
    watcher._reload_custom_tool(root/'approved.py')
    assert marker.read_text() == 'x'
    monkeypatch.setenv('ROMS_MCP_HOT_RELOAD','1')
    watcher._reload_custom_tool(root/'approved.py')
    assert marker.read_text() == 'xx'
    assert not plugin_allowed(root/'unapproved.py',root)
    monkeypatch.setenv('ROMS_MCP_PLUGINS','../approved')
    with pytest.raises(ValueError):plugin_allowed(root/'approved.py',root)


def test_plugin_symlinks_cannot_escape_allowlist(tmp_path, monkeypatch):
    root=tmp_path/'custom_tools';root.mkdir()
    outside=tmp_path/'outside.py';outside.write_text('raise RuntimeError()')
    try:(root/'approved.py').symlink_to(outside)
    except OSError:pytest.skip('Host does not permit symlinks')
    monkeypatch.setenv('ROMS_MCP_PROFILE','local')
    monkeypatch.setenv('ROMS_MCP_PLUGINS','approved')
    assert not plugin_allowed(root/'approved.py',root)




def test_read_only_keeps_search_and_denies_unknown_tools():
    async def check():
        policy = MCPPolicy(profile='read_only')
        async def next_call(ctx): return 'search result'
        assert await policy.on_call_tool(context('search_knowledge_base'), next_call) == 'search result'
        with pytest.raises(ToolError, match='read_only'):
            await policy.on_call_tool(context('future_unreviewed_tool'), next_call)
    asyncio.run(check())


def test_cancellation_releases_concurrency_slot():
    async def check():
        entered = asyncio.Event()
        policy = MCPPolicy(profile='read_only', max_concurrent=1)
        async def wait(ctx):
            entered.set()
            await asyncio.Event().wait()
        running = asyncio.create_task(policy.on_call_tool(context('memory_get'), wait))
        await entered.wait()
        running.cancel()
        with pytest.raises(asyncio.CancelledError): await running
        assert policy.inflight == 0
    asyncio.run(check())


def test_all_registered_tools_have_explicit_conservative_metadata():
    import ast
    from app.mcp_annotations import READ_TOOLS, WRITE_TOOLS
    root = Path(__file__).resolve().parents[1]
    paths = [root/'app/server.py', root/'app/mojo_bridge.py', root/'app/memory_tools.py', root/'app/knowledge_skill_tools.py',
             *sorted((root/'custom_tools').glob('*.py'))]
    names = set()
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr == 'tool':
                        names.add(node.name)
                        assert any(keyword.arg == 'annotations' for keyword in decorator.keywords), node.name
    assert names == READ_TOOLS | WRITE_TOOLS
    assert not READ_TOOLS & WRITE_TOOLS
    assert tool_annotations('future_plugin_tool')['openWorldHint'] is True
    assert tool_annotations('roms_snapshot_rewind')['destructiveHint'] is True
    assert tool_annotations('search_knowledge_base')['readOnlyHint'] is True
    assert tool_annotations('search_knowledge_base')['openWorldHint'] is True


def test_native_bridge_enforces_the_same_read_only_boundary(monkeypatch):
    from app.mojo_bridge import build_server
    calls = []
    class Native:
        def pack_context(self, *args): return []
        def search_knowledge_base(self, query, limit): return 'native search'
        def create_support_ticket(self, *args):
            calls.append(args)
            return 'unexpected write'
    monkeypatch.setenv('ROMS_MCP_PROFILE', 'read_only')
    server = build_server(Native())
    async def check():
        async with Client(server) as client:
            assert (await client.call_tool('search_knowledge_base', {'query':'test'})).content[0].text == 'native search'
            with pytest.raises(ToolError, match='read_only'):
                await client.call_tool('create_support_ticket', {'ticket_id':'test','email':'fixture@example.invalid','summary':'fixture'})
    asyncio.run(check())
    assert not calls
